from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from player_state_engine.models.quantile import NONNEGATIVE_TARGETS


def _qcol(target: str, quantile: float) -> str:
    return f"{target}_q{int(round(quantile * 100)):02d}"


@dataclass(slots=True)
class ConformalCorrection:
    target: str
    position: str
    quantile: float
    rows: int
    raw_correction: float
    shrunk_correction: float
    raw_tail_scale: float
    shrunk_tail_scale: float


def _best_tail_scale(
    actual: np.ndarray, median: np.ndarray, tail: np.ndarray, quantile: float
) -> float:
    valid = np.isfinite(actual) & np.isfinite(median) & np.isfinite(tail)
    if valid.sum() < 10 or np.allclose(median[valid], tail[valid]):
        return 1.0
    grid = np.concatenate(
        [
            np.linspace(0.05, 0.95, 19),
            np.linspace(1.0, 2.0, 21),
            np.linspace(2.2, 4.0, 10),
        ]
    )
    errors: list[tuple[float, float]] = []
    for scale in grid:
        candidate = median[valid] + scale * (tail[valid] - median[valid])
        empirical = float(np.mean(actual[valid] <= candidate))
        errors.append((abs(empirical - quantile), float(scale)))
    return min(errors, key=lambda item: (item[0], abs(item[1] - 1.0)))[1]


@dataclass
class TargetPositionConformalCalibrator:
    """Earlier-residual quantile calibration with position-aware tail scaling.

    Additive residual corrections calibrate location. Tail scales then widen or
    contract q10/q90 around q50 to address interval under/overcoverage. Sparse
    positions are partially pooled toward target-wide corrections and scales.
    """

    quantiles: tuple[float, ...] = (0.1, 0.5, 0.9)
    min_group_rows: int = 75
    shrinkage_rows: float = 200.0
    corrections: dict[tuple[str, str, float], float] = field(default_factory=dict)
    target_fallbacks: dict[tuple[str, float], float] = field(default_factory=dict)
    tail_scales: dict[tuple[str, str, float], float] = field(default_factory=dict)
    target_scale_fallbacks: dict[tuple[str, float], float] = field(default_factory=dict)
    diagnostics: list[ConformalCorrection] = field(default_factory=list)
    fitted_through_season: int | None = None

    def _weight(self, rows: int) -> float:
        if rows < self.min_group_rows:
            return rows / max(self.min_group_rows, 1)
        return rows / (rows + self.shrinkage_rows)

    def fit(
        self,
        predictions: pd.DataFrame,
        target: str,
        *,
        method: str = "quantile_engine",
        through_season: int | None = None,
    ) -> TargetPositionConformalCalibrator:
        data = predictions.copy()
        if "method" in data.columns:
            data = data.loc[data["method"] == method]
        if through_season is not None and "season" in data.columns:
            data = data.loc[data["season"] <= through_season]
        if data.empty:
            raise ValueError("No calibration rows remain after method/season filtering.")
        required = {"actual", "position", *(_qcol(target, q) for q in self.quantiles)}
        missing = required - set(data.columns)
        if missing:
            raise ValueError(f"Calibration predictions missing columns: {sorted(missing)}")

        self.corrections = {}
        self.target_fallbacks = {}
        self.tail_scales = {}
        self.target_scale_fallbacks = {}
        self.diagnostics = []
        self.fitted_through_season = through_season

        sorted_q = tuple(sorted(float(q) for q in self.quantiles))
        median_q = min(sorted_q, key=lambda q: abs(q - 0.5))
        corrected = data[["actual", "position"]].copy()

        for quantile in sorted_q:
            pred_col = _qcol(target, quantile)
            valid = (
                data[["actual", pred_col, "position"]].replace([np.inf, -np.inf], np.nan).dropna()
            )
            residual = valid["actual"].astype(float) - valid[pred_col].astype(float)
            fallback = float(residual.quantile(quantile)) if not residual.empty else 0.0
            self.target_fallbacks[(target, quantile)] = fallback
            corrected[pred_col] = pd.to_numeric(data[pred_col], errors="coerce") + fallback

            for position, subset in valid.assign(_residual=residual).groupby(
                "position", dropna=False
            ):
                rows = len(subset)
                raw = float(subset["_residual"].quantile(quantile)) if rows else fallback
                weight = self._weight(rows)
                shrunk = float(weight * raw + (1.0 - weight) * fallback)
                self.corrections[(target, str(position), quantile)] = shrunk
                index = data["position"].astype(str).eq(str(position))
                corrected.loc[index, pred_col] = (
                    pd.to_numeric(data.loc[index, pred_col], errors="coerce") + shrunk
                )

        median_col = _qcol(target, median_q)
        actual_all = pd.to_numeric(corrected["actual"], errors="coerce").to_numpy(float)
        median_all = pd.to_numeric(corrected[median_col], errors="coerce").to_numpy(float)

        raw_scale_by_key: dict[tuple[str, str, float], float] = {}
        for quantile in sorted_q:
            if quantile == median_q:
                self.target_scale_fallbacks[(target, quantile)] = 1.0
                continue
            tail_col = _qcol(target, quantile)
            tail_all = pd.to_numeric(corrected[tail_col], errors="coerce").to_numpy(float)
            fallback_scale = _best_tail_scale(actual_all, median_all, tail_all, quantile)
            self.target_scale_fallbacks[(target, quantile)] = fallback_scale
            for position, subset in corrected.groupby("position", dropna=False):
                rows = len(subset)
                actual = pd.to_numeric(subset["actual"], errors="coerce").to_numpy(float)
                median = pd.to_numeric(subset[median_col], errors="coerce").to_numpy(float)
                tail = pd.to_numeric(subset[tail_col], errors="coerce").to_numpy(float)
                raw_scale = _best_tail_scale(actual, median, tail, quantile)
                weight = self._weight(rows)
                shrunk_scale = float(weight * raw_scale + (1.0 - weight) * fallback_scale)
                key = (target, str(position), quantile)
                self.tail_scales[key] = shrunk_scale
                raw_scale_by_key[key] = raw_scale

        for quantile in sorted_q:
            for position, subset in data.groupby("position", dropna=False):
                key = (target, str(position), quantile)
                correction = self.corrections.get(key, self.target_fallbacks[(target, quantile)])
                self.diagnostics.append(
                    ConformalCorrection(
                        target=target,
                        position=str(position),
                        quantile=quantile,
                        rows=len(subset),
                        raw_correction=float(
                            (
                                pd.to_numeric(subset["actual"], errors="coerce")
                                - pd.to_numeric(subset[_qcol(target, quantile)], errors="coerce")
                            ).quantile(quantile)
                        ),
                        shrunk_correction=correction,
                        raw_tail_scale=raw_scale_by_key.get(key, 1.0),
                        shrunk_tail_scale=self.tail_scales.get(
                            key, self.target_scale_fallbacks.get((target, quantile), 1.0)
                        ),
                    )
                )
        return self

    def transform(self, predictions: pd.DataFrame, target: str) -> pd.DataFrame:
        if not self.target_fallbacks:
            raise RuntimeError("Calibrator has not been fitted.")
        output = predictions.copy()
        positions = output.get("position", pd.Series("ALL", index=output.index)).astype(str)
        sorted_q = tuple(sorted(float(q) for q in self.quantiles))
        median_q = min(sorted_q, key=lambda q: abs(q - 0.5))
        adjusted: dict[float, np.ndarray] = {}
        for quantile in sorted_q:
            column = _qcol(target, quantile)
            if column not in output:
                raise ValueError(f"Prediction frame is missing {column!r}.")
            fallback = self.target_fallbacks[(target, quantile)]
            correction = np.array(
                [
                    self.corrections.get((target, position, quantile), fallback)
                    for position in positions
                ],
                dtype=float,
            )
            adjusted[quantile] = (
                pd.to_numeric(output[column], errors="coerce").to_numpy(float) + correction
            )

        median = adjusted[median_q]
        for quantile in sorted_q:
            if quantile == median_q:
                continue
            fallback_scale = self.target_scale_fallbacks.get((target, quantile), 1.0)
            scale = np.array(
                [
                    self.tail_scales.get((target, position, quantile), fallback_scale)
                    for position in positions
                ],
                dtype=float,
            )
            adjusted[quantile] = median + scale * (adjusted[quantile] - median)

        columns = [_qcol(target, q) for q in sorted_q]
        monotonic = np.sort(np.vstack([adjusted[q] for q in sorted_q]), axis=0).T
        if target in NONNEGATIVE_TARGETS:
            monotonic = np.clip(monotonic, 0.0, None)
        output[columns] = monotonic
        output["conformal_fitted_through_season"] = self.fitted_through_season
        output["conformal_applied"] = 1
        return output

    def diagnostics_frame(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(item) for item in self.diagnostics])

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> TargetPositionConformalCalibrator:
        calibrator = joblib.load(path)
        if not isinstance(calibrator, cls):
            raise TypeError("Saved object is not a TargetPositionConformalCalibrator.")
        return calibrator


def apply_earlier_season_conformal(
    predictions: pd.DataFrame,
    target: str,
    quantiles: Iterable[float] = (0.1, 0.5, 0.9),
    *,
    method: str = "quantile_engine",
    minimum_calibration_seasons: int = 1,
    min_group_rows: int = 75,
    shrinkage_rows: float = 200.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calibrate each held-out season using residuals from earlier seasons only."""

    data = predictions.loc[predictions["method"] == method].copy()
    if data.empty:
        raise ValueError(f"No rows found for method {method!r}.")
    seasons = sorted(int(s) for s in data["season"].dropna().unique())
    output_parts: list[pd.DataFrame] = []
    diagnostic_parts: list[pd.DataFrame] = []

    for season in seasons:
        test = data.loc[data["season"] == season].copy()
        previous = [s for s in seasons if s < season]
        if len(previous) < minimum_calibration_seasons:
            test["method"] = f"{method}_conformal"
            test["conformal_applied"] = 0
            test["conformal_fitted_through_season"] = pd.NA
            output_parts.append(test)
            continue
        calibrator = TargetPositionConformalCalibrator(
            quantiles=tuple(float(q) for q in quantiles),
            min_group_rows=min_group_rows,
            shrinkage_rows=shrinkage_rows,
        ).fit(
            data.loc[data["season"] < season], target, method=method, through_season=max(previous)
        )
        calibrated = calibrator.transform(test, target)
        calibrated["method"] = f"{method}_conformal"
        output_parts.append(calibrated)
        diagnostics = calibrator.diagnostics_frame()
        diagnostics["test_season"] = season
        diagnostic_parts.append(diagnostics)

    return (
        pd.concat(output_parts, ignore_index=True),
        pd.concat(diagnostic_parts, ignore_index=True) if diagnostic_parts else pd.DataFrame(),
    )
