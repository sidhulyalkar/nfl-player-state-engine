from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not valid.any():
        return 0.0
    values = values[valid]
    weights = weights[valid]
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cumulative = np.cumsum(weights)
    threshold = float(np.clip(quantile, 0.0, 1.0)) * cumulative[-1]
    index = int(np.searchsorted(cumulative, threshold, side="left"))
    return float(values[min(index, len(values) - 1)])


def _pinball(actual: np.ndarray, predicted: np.ndarray, quantile: float) -> float:
    error = actual - predicted
    return float(np.mean(np.maximum(quantile * error, (quantile - 1.0) * error)))


def _order_quantile_triplet(
    frame: pd.DataFrame,
    columns: tuple[str, str, str],
) -> np.ndarray:
    """Repair crossed q10/q50/q90 rows in-place and return a per-row repair mask."""

    values = frame.loc[:, list(columns)].to_numpy(float)
    crossed = (values[:, 0] > values[:, 1]) | (values[:, 1] > values[:, 2])
    values.sort(axis=1)
    frame.loc[:, list(columns)] = values
    return crossed


def calibration_report(frame: pd.DataFrame) -> dict[str, float]:
    required = {"actual", "q10", "q50", "q90"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Calibration report missing columns: {sorted(missing)}")
    clean = frame[list(required)].replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return {
            "rows": 0.0,
            "q10_empirical": float("nan"),
            "q50_empirical": float("nan"),
            "q90_empirical": float("nan"),
            "interval_coverage": float("nan"),
            "interval_width": float("nan"),
        }
    actual = clean["actual"].to_numpy(float)
    q10 = clean["q10"].to_numpy(float)
    q50 = clean["q50"].to_numpy(float)
    q90 = clean["q90"].to_numpy(float)
    return {
        "rows": float(len(clean)),
        "q10_empirical": float(np.mean(actual <= q10)),
        "q50_empirical": float(np.mean(actual <= q50)),
        "q90_empirical": float(np.mean(actual <= q90)),
        "interval_coverage": float(np.mean((actual >= q10) & (actual <= q90))),
        "interval_width": float(np.mean(q90 - q10)),
    }


@dataclass(frozen=True, slots=True)
class ConformalAdjustment:
    median_bias: float
    interval_expansion: float
    rows: int
    effective_weight: float


@dataclass
class RecencyWeightedConditionalConformal:
    """Recency-weighted conditional calibration for q10/q50/q90 forecasts.

    Fitting is strictly historical. Sparse position/target groups back off through a hierarchy
    to a global adjustment. The calibrator reports both coverage and sharpness so wider tails
    cannot masquerade as a free calibration win.

    Because recency weights and hierarchical shrinkage intentionally relax exchangeability, this
    is a conformal-style research calibrator, not a claim of exact finite-sample coverage.
    """

    target_coverage: float = 0.80
    half_life_days: float = 365.0
    min_group_rows: int = 100
    shrinkage_rows: float = 250.0
    group_hierarchy: tuple[tuple[str, ...], ...] = (
        (),
        ("position",),
        ("target",),
        ("position", "target"),
    )
    adjustments: dict[tuple[tuple[str, ...], tuple[str, ...]], ConformalAdjustment] = field(
        default_factory=dict
    )
    fitted_through: pd.Timestamp | None = None

    def _recency_weights(self, data: pd.DataFrame) -> np.ndarray:
        if "prediction_timestamp" not in data:
            return np.ones(len(data), dtype=float)
        timestamps = pd.to_datetime(data["prediction_timestamp"], utc=True, errors="coerce")
        valid = timestamps.notna()
        if not valid.any():
            return np.ones(len(data), dtype=float)
        reference = timestamps.loc[valid].max()
        self.fitted_through = reference
        age_days = (
            (reference - timestamps.fillna(reference)).dt.total_seconds().to_numpy(float) / 86400.0
        )
        return np.power(0.5, np.maximum(age_days, 0.0) / max(self.half_life_days, 1e-6))

    def _fit_subset(self, subset: pd.DataFrame, weights: np.ndarray) -> ConformalAdjustment:
        actual = subset["actual"].to_numpy(float)
        q10 = subset["q10"].to_numpy(float)
        q50 = subset["q50"].to_numpy(float)
        q90 = subset["q90"].to_numpy(float)
        median_bias = _weighted_quantile(actual - q50, weights, 0.50)
        shifted_q10 = q10 + median_bias
        shifted_q90 = q90 + median_bias
        nonconformity = np.maximum.reduce(
            [shifted_q10 - actual, actual - shifted_q90, np.zeros(len(subset), dtype=float)]
        )
        expansion = max(
            0.0,
            _weighted_quantile(nonconformity, weights, float(self.target_coverage)),
        )
        return ConformalAdjustment(
            median_bias=float(median_bias),
            interval_expansion=float(expansion),
            rows=len(subset),
            effective_weight=float(np.sum(weights)),
        )

    def fit(self, history: pd.DataFrame) -> RecencyWeightedConditionalConformal:
        required = {"actual", "q10", "q50", "q90"}
        missing = required - set(history.columns)
        if missing:
            raise ValueError(f"Conformal history missing columns: {sorted(missing)}")
        data = history.copy()
        for column in required:
            data[column] = pd.to_numeric(data[column], errors="coerce")
        data = (
            data.replace([np.inf, -np.inf], np.nan)
            .dropna(subset=list(required))
            .reset_index(drop=True)
        )
        if data.empty:
            raise ValueError("No finite calibration rows remain")
        _order_quantile_triplet(data, ("q10", "q50", "q90"))
        weights = self._recency_weights(data)
        data["_weight"] = weights
        self.adjustments = {}

        global_adjustment = self._fit_subset(data, weights)
        self.adjustments[((), ())] = global_adjustment
        for level in self.group_hierarchy:
            if not level:
                continue
            if any(column not in data for column in level):
                continue
            grouper: str | list[str] = level[0] if len(level) == 1 else list(level)
            for values, subset in data.groupby(grouper, dropna=False):
                key_values = (
                    (str(values),)
                    if len(level) == 1
                    else tuple(str(value) for value in values)
                )
                indexes = subset.index.to_numpy()
                raw = self._fit_subset(subset, data.loc[indexes, "_weight"].to_numpy(float))
                if raw.rows < self.min_group_rows:
                    continue
                parent = self._best_adjustment(
                    dict(zip(level, key_values, strict=True)), levels=level[:-1]
                )
                strength = raw.rows / (raw.rows + self.shrinkage_rows)
                self.adjustments[(level, key_values)] = ConformalAdjustment(
                    median_bias=float(
                        strength * raw.median_bias + (1.0 - strength) * parent.median_bias
                    ),
                    interval_expansion=float(
                        strength * raw.interval_expansion
                        + (1.0 - strength) * parent.interval_expansion
                    ),
                    rows=raw.rows,
                    effective_weight=raw.effective_weight,
                )
        return self

    def _best_adjustment(
        self,
        context: dict[str, str],
        *,
        levels: Sequence[str] | None = None,
    ) -> ConformalAdjustment:
        candidate_levels = self.group_hierarchy
        if levels is not None:
            allowed = set(levels)
            candidate_levels = tuple(
                level for level in candidate_levels if set(level).issubset(allowed)
            )
        best = self.adjustments.get(((), ()))
        if best is None:
            raise RuntimeError("Calibrator has not been fitted")
        best_size = 0
        for level in candidate_levels:
            if not level or any(column not in context for column in level):
                continue
            values = tuple(str(context[column]) for column in level)
            adjustment = self.adjustments.get((level, values))
            if adjustment is not None and len(level) >= best_size:
                best = adjustment
                best_size = len(level)
        return best

    def transform(self, forecasts: pd.DataFrame) -> pd.DataFrame:
        if not self.adjustments:
            raise RuntimeError("Calibrator has not been fitted")
        required = {"q10", "q50", "q90"}
        missing = required - set(forecasts.columns)
        if missing:
            raise ValueError(f"Forecast frame missing columns: {sorted(missing)}")
        out = forecasts.copy()
        for column in required:
            out[column] = pd.to_numeric(out[column], errors="coerce")
        crossed = _order_quantile_triplet(out, ("q10", "q50", "q90"))
        q10 = out["q10"].to_numpy(float)
        q50 = out["q50"].to_numpy(float)
        q90 = out["q90"].to_numpy(float)
        biases = np.zeros(len(out), dtype=float)
        expansions = np.zeros(len(out), dtype=float)
        for row_number, (_, row) in enumerate(out.iterrows()):
            context = {
                column: str(row[column])
                for column in ("position", "target")
                if column in out
            }
            adjustment = self._best_adjustment(context)
            biases[row_number] = adjustment.median_bias
            expansions[row_number] = adjustment.interval_expansion
        stacked = np.column_stack(
            [q10 + biases - expansions, q50 + biases, q90 + biases + expansions]
        )
        stacked.sort(axis=1)
        out[["q10", "q50", "q90"]] = stacked
        out["conditional_conformal_applied"] = 1
        out["conformal_input_quantiles_reordered"] = crossed
        out["conformal_interval_expansion"] = expansions
        out["conformal_median_bias"] = biases
        out["conformal_fitted_through"] = self.fitted_through
        return out


@dataclass(frozen=True, slots=True)
class FusionWeights:
    experts: tuple[str, ...]
    weights: tuple[float, ...]
    rows: int
    level: tuple[str, ...]
    values: tuple[str, ...]

    def as_dict(self) -> dict[str, float]:
        return dict(zip(self.experts, self.weights, strict=True))


@dataclass
class HierarchicalForecastFusion:
    """Historically learned convex fusion across auditable forecast experts.

    Expected wide columns are ``<expert>_q10``, ``<expert>_q50``, ``<expert>_q90`` plus
    ``actual`` during fitting. Context-specific weights shrink toward their parent hierarchy.
    Expert predictions are retained in transformed output so disagreement remains observable.

    A weak inverse-standalone-loss prior resolves non-identifiable convex mixtures. It acts as
    a tie-break, not a shortcut around the primary pinball objective: complementary experts
    still earn weight when their blend improves historical quantile loss. Crossed expert
    quantiles are repaired identically during fitting and inference and surfaced as diagnostics.
    """

    experts: tuple[str, ...] = ("direct", "world", "consensus")
    min_group_rows: int = 150
    shrinkage_rows: float = 300.0
    loss_prior_strength: float = 0.01
    hierarchy: tuple[tuple[str, ...], ...] = (
        (),
        ("position",),
        ("position", "target"),
        ("position", "target", "forecast_horizon"),
        ("position", "target", "forecast_horizon", "regime_maturity_bucket"),
    )
    fitted_weights: dict[tuple[tuple[str, ...], tuple[str, ...]], FusionWeights] = field(
        default_factory=dict
    )
    research_only: bool = True

    def _required_columns(self, include_actual: bool) -> set[str]:
        required = {
            f"{expert}_q{quantile}"
            for expert in self.experts
            for quantile in (10, 50, 90)
        }
        if include_actual:
            required.add("actual")
        return required

    def _repair_expert_quantiles(self, data: pd.DataFrame) -> np.ndarray:
        repaired = np.zeros(len(data), dtype=bool)
        for expert in self.experts:
            repaired |= _order_quantile_triplet(
                data,
                (f"{expert}_q10", f"{expert}_q50", f"{expert}_q90"),
            )
        return repaired

    def _standalone_loss_prior(
        self,
        actual: np.ndarray,
        predictions: dict[int, np.ndarray],
    ) -> np.ndarray:
        losses = np.asarray(
            [
                np.mean(
                    [
                        _pinball(actual, predictions[quantile][:, expert_index], quantile / 100.0)
                        for quantile in (10, 50, 90)
                    ]
                )
                for expert_index in range(len(self.experts))
            ],
            dtype=float,
        )
        floor = max(float(np.min(losses)) * 0.05, 1e-6)
        inverse = 1.0 / np.maximum(losses + floor, 1e-12)
        return inverse / max(float(inverse.sum()), 1e-12)

    def _fit_weights(self, data: pd.DataFrame) -> np.ndarray:
        actual = data["actual"].to_numpy(float)
        predictions = {
            quantile: np.column_stack(
                [data[f"{expert}_q{quantile}"].to_numpy(float) for expert in self.experts]
            )
            for quantile in (10, 50, 90)
        }
        loss_prior = self._standalone_loss_prior(actual, predictions)

        def objective(weights: np.ndarray) -> float:
            total = 0.0
            for quantile in (10, 50, 90):
                blended = predictions[quantile] @ weights
                total += _pinball(actual, blended, quantile / 100.0)
            regularization = max(float(self.loss_prior_strength), 0.0) * float(
                np.sum((weights - loss_prior) ** 2)
            )
            return total / 3.0 + regularization

        result = minimize(
            objective,
            loss_prior,
            method="SLSQP",
            bounds=[(0.0, 1.0)] * len(self.experts),
            constraints={"type": "eq", "fun": lambda weights: float(np.sum(weights) - 1.0)},
            options={"maxiter": 250, "ftol": 1e-10},
        )
        if not result.success or not np.isfinite(result.fun):
            return loss_prior
        weights = np.maximum(np.asarray(result.x, dtype=float), 0.0)
        return weights / max(float(weights.sum()), 1e-12)

    def fit(self, history: pd.DataFrame) -> HierarchicalForecastFusion:
        missing = self._required_columns(include_actual=True) - set(history.columns)
        if missing:
            raise ValueError(f"Fusion history missing columns: {sorted(missing)}")
        data = history.copy()
        numeric = list(self._required_columns(include_actual=True))
        for column in numeric:
            data[column] = pd.to_numeric(data[column], errors="coerce")
        data = (
            data.replace([np.inf, -np.inf], np.nan)
            .dropna(subset=numeric)
            .reset_index(drop=True)
        )
        if data.empty:
            raise ValueError("No finite fusion rows remain")
        self._repair_expert_quantiles(data)
        self.fitted_weights = {}
        global_weights = self._fit_weights(data)
        self.fitted_weights[((), ())] = FusionWeights(
            self.experts, tuple(float(value) for value in global_weights), len(data), (), ()
        )

        for level in self.hierarchy:
            if not level or any(column not in data for column in level):
                continue
            grouper: str | list[str] = level[0] if len(level) == 1 else list(level)
            for values, subset in data.groupby(grouper, dropna=False):
                if len(subset) < self.min_group_rows:
                    continue
                key_values = (
                    (str(values),)
                    if len(level) == 1
                    else tuple(str(value) for value in values)
                )
                raw = self._fit_weights(subset)
                context = dict(zip(level, key_values, strict=True))
                parent = self._best_weights(context, maximum_depth=len(level) - 1)
                strength = len(subset) / (len(subset) + self.shrinkage_rows)
                shrunk = strength * raw + (1.0 - strength) * np.asarray(
                    parent.weights, dtype=float
                )
                shrunk = np.maximum(shrunk, 0.0)
                shrunk = shrunk / max(float(shrunk.sum()), 1e-12)
                self.fitted_weights[(level, key_values)] = FusionWeights(
                    self.experts,
                    tuple(float(value) for value in shrunk),
                    len(subset),
                    level,
                    key_values,
                )
        return self

    def _best_weights(
        self, context: dict[str, str], *, maximum_depth: int | None = None
    ) -> FusionWeights:
        best = self.fitted_weights.get(((), ()))
        if best is None:
            raise RuntimeError("Fusion has not been fitted")
        best_depth = 0
        for level in self.hierarchy:
            if not level:
                continue
            if maximum_depth is not None and len(level) > maximum_depth:
                continue
            if any(column not in context for column in level):
                continue
            key = (level, tuple(str(context[column]) for column in level))
            candidate = self.fitted_weights.get(key)
            if candidate is not None and len(level) >= best_depth:
                best = candidate
                best_depth = len(level)
        return best

    def transform(self, forecasts: pd.DataFrame) -> pd.DataFrame:
        if not self.fitted_weights:
            raise RuntimeError("Fusion has not been fitted")
        missing = self._required_columns(include_actual=False) - set(forecasts.columns)
        if missing:
            raise ValueError(f"Fusion forecast frame missing columns: {sorted(missing)}")
        out = forecasts.copy()
        for column in self._required_columns(include_actual=False):
            out[column] = pd.to_numeric(out[column], errors="coerce")
        repaired = self._repair_expert_quantiles(out)
        blended = np.zeros((len(out), 3), dtype=float)
        selected: list[FusionWeights] = []
        context_columns = {
            "position",
            "target",
            "forecast_horizon",
            "regime_maturity_bucket",
        }
        for row_number, (_, row) in enumerate(out.iterrows()):
            context = {
                column: str(row[column]) for column in context_columns if column in out
            }
            weights = self._best_weights(context)
            selected.append(weights)
            weight_array = np.asarray(weights.weights, dtype=float)
            for quantile_index, quantile in enumerate((10, 50, 90)):
                values = np.asarray(
                    [float(row[f"{expert}_q{quantile}"]) for expert in self.experts],
                    dtype=float,
                )
                blended[row_number, quantile_index] = float(values @ weight_array)
        blended.sort(axis=1)
        out[["q10", "q50", "q90"]] = blended
        q50_matrix = np.column_stack(
            [
                pd.to_numeric(out[f"{expert}_q50"], errors="coerce").to_numpy(float)
                for expert in self.experts
            ]
        )
        out["expert_disagreement_range"] = np.ptp(q50_matrix, axis=1)
        out["expert_disagreement_sd"] = np.std(q50_matrix, axis=1)
        out["fusion_input_quantiles_reordered"] = repaired
        out["fusion_level"] = [
            "/".join(item.level) if item.level else "global" for item in selected
        ]
        for expert_index, expert in enumerate(self.experts):
            out[f"fusion_weight_{expert}"] = [item.weights[expert_index] for item in selected]
        out["fusion_research_only"] = int(self.research_only)
        return out

    def weight_frame(self) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for item in self.fitted_weights.values():
            row: dict[str, object] = {
                "level": "/".join(item.level) if item.level else "global",
                "values": "/".join(item.values),
                "rows": item.rows,
            }
            row.update({f"weight_{key}": value for key, value in item.as_dict().items()})
            rows.append(row)
        return pd.DataFrame(rows)
