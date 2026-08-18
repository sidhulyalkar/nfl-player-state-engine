from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_QUANTILES = (0.10, 0.50, 0.90)
_Q_NAMES = ("q10", "q50", "q90")


def _chronology(frame: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(frame["season"], errors="coerce") * 25 + pd.to_numeric(
        frame["week"], errors="coerce"
    )


def _resolve_quantile_columns(frame: pd.DataFrame) -> dict[str, str]:
    candidates = {
        "q10": ("q10", "fantasy_q10", "fantasy_points_q10", "season_points_q10", "valuation_points_q10"),
        "q50": ("q50", "fantasy_q50", "fantasy_points_q50", "season_points_q50", "valuation_points_q50"),
        "q90": ("q90", "fantasy_q90", "fantasy_points_q90", "season_points_q90", "valuation_points_q90"),
    }
    resolved: dict[str, str] = {}
    for target, options in candidates.items():
        column = next((option for option in options if option in frame), None)
        if column is None:
            raise ValueError(f"Projection frame is missing a recognizable {target} column")
        resolved[target] = column
    return resolved


def _actual_column(frame: pd.DataFrame) -> str:
    column = next(
        (
            candidate
            for candidate in ("fantasy_points_ppr", "fantasy_points", "points", "actual")
            if candidate in frame
        ),
        None,
    )
    if column is None:
        raise ValueError("Actual outcomes need fantasy_points_ppr, fantasy_points, points, or actual")
    return column


def _keys(*frames: pd.DataFrame) -> list[str]:
    common = set.intersection(*(set(frame.columns) for frame in frames))
    keys = [column for column in ("season", "week", "player_id") if column in common]
    if keys != ["season", "week", "player_id"]:
        raise ValueError("Blend benchmark requires season, week, and player_id in every frame")
    return keys


def _pinball(actual: np.ndarray, prediction: np.ndarray, quantile: float) -> float:
    error = actual - prediction
    return float(np.mean(np.maximum(quantile * error, (quantile - 1.0) * error)))


def _evaluate(frame: pd.DataFrame, prefix: str, actual_column: str = "actual") -> dict[str, float]:
    y = pd.to_numeric(frame[actual_column], errors="coerce").to_numpy(dtype=float)
    predictions = {
        name: pd.to_numeric(frame[f"{prefix}_{name}"], errors="coerce").to_numpy(dtype=float)
        for name in _Q_NAMES
    }
    valid = np.isfinite(y)
    for values in predictions.values():
        valid &= np.isfinite(values)
    if not valid.any():
        raise ValueError("No valid quantile rows to evaluate")
    y = y[valid]
    values = {name: prediction[valid] for name, prediction in predictions.items()}
    losses = [
        _pinball(y, values[name], quantile)
        for name, quantile in zip(_Q_NAMES, _QUANTILES, strict=True)
    ]
    return {
        "rows": float(len(y)),
        "pinball_loss": float(np.mean(losses)),
        "median_mae": float(np.mean(np.abs(y - values["q50"]))),
        "q10_q90_coverage": float(((y >= values["q10"]) & (y <= values["q90"])).mean()),
        "interval_width": float(np.mean(values["q90"] - values["q10"])),
    }


def align_projection_frames(
    direct: pd.DataFrame,
    generative: pd.DataFrame,
    actuals: pd.DataFrame,
) -> pd.DataFrame:
    keys = _keys(direct, generative, actuals)
    direct_columns = _resolve_quantile_columns(direct)
    generative_columns = _resolve_quantile_columns(generative)
    actual_column = _actual_column(actuals)

    direct_keep = direct[keys + list(dict.fromkeys(direct_columns.values()))].copy()
    direct_keep = direct_keep.rename(
        columns={column: f"direct_{target}" for target, column in direct_columns.items()}
    )
    generative_keep_columns = keys + list(dict.fromkeys(generative_columns.values()))
    if "position" in generative:
        generative_keep_columns.append("position")
    generative_keep = generative[generative_keep_columns].copy().rename(
        columns={column: f"generative_{target}" for target, column in generative_columns.items()}
    )
    actual_keep_columns = keys + [actual_column]
    if "position" in actuals and "position" not in generative_keep:
        actual_keep_columns.append("position")
    actual_keep = actuals[actual_keep_columns].copy().rename(columns={actual_column: "actual"})

    joined = direct_keep.merge(generative_keep, on=keys, how="inner")
    joined = joined.merge(actual_keep, on=keys, how="inner", suffixes=("", "_actual"))
    if "position_actual" in joined and "position" not in joined:
        joined["position"] = joined["position_actual"]
    joined["player_id"] = joined["player_id"].astype(str)
    return joined


@dataclass(slots=True)
class QuantileBlendCalibrator:
    """Learn direct-vs-generative blend weights only from historical prediction rows."""

    grid: tuple[float, ...] = tuple(np.linspace(0.0, 1.0, 21).tolist())
    min_position_rows: int = 100
    global_direct_weight: float = 0.5
    position_direct_weights: dict[str, float] = field(default_factory=dict)
    fitted: bool = False

    @staticmethod
    def _blended(frame: pd.DataFrame, direct_weight: float) -> pd.DataFrame:
        result = frame.copy()
        weight = float(np.clip(direct_weight, 0.0, 1.0))
        for name in _Q_NAMES:
            result[f"blend_{name}"] = (
                weight * pd.to_numeric(result[f"direct_{name}"], errors="coerce")
                + (1.0 - weight) * pd.to_numeric(result[f"generative_{name}"], errors="coerce")
            )
        ordered = np.sort(result[[f"blend_{name}" for name in _Q_NAMES]].to_numpy(dtype=float), axis=1)
        for index, name in enumerate(_Q_NAMES):
            result[f"blend_{name}"] = ordered[:, index]
        return result

    def _best_weight(self, frame: pd.DataFrame) -> float:
        best_weight = 0.5
        best_loss = float("inf")
        for weight in self.grid:
            candidate = self._blended(frame, weight)
            try:
                loss = _evaluate(candidate, "blend")["pinball_loss"]
            except ValueError:
                continue
            if loss < best_loss - 1e-12:
                best_loss = loss
                best_weight = float(weight)
        return best_weight

    def fit(self, aligned_history: pd.DataFrame) -> QuantileBlendCalibrator:
        if len(aligned_history) < 50:
            raise ValueError("Blend calibrator requires at least 50 historical aligned rows")
        self.global_direct_weight = self._best_weight(aligned_history)
        self.position_direct_weights = {}
        if "position" in aligned_history:
            for position, group in aligned_history.groupby("position", dropna=False):
                if len(group) >= int(self.min_position_rows):
                    self.position_direct_weights[str(position)] = self._best_weight(group)
        self.fitted = True
        return self

    def transform(self, aligned_future: pd.DataFrame) -> pd.DataFrame:
        if not self.fitted:
            raise RuntimeError("Blend calibrator must be fitted before transform")
        result = aligned_future.copy()
        result["direct_weight"] = float(self.global_direct_weight)
        if "position" in result:
            mapped = result["position"].astype(str).map(self.position_direct_weights)
            result["direct_weight"] = mapped.fillna(result["direct_weight"])
        for name in _Q_NAMES:
            result[f"blend_{name}"] = (
                result["direct_weight"] * pd.to_numeric(result[f"direct_{name}"], errors="coerce")
                + (1.0 - result["direct_weight"])
                * pd.to_numeric(result[f"generative_{name}"], errors="coerce")
            )
        ordered = np.sort(result[[f"blend_{name}" for name in _Q_NAMES]].to_numpy(dtype=float), axis=1)
        for index, name in enumerate(_Q_NAMES):
            result[f"blend_{name}"] = ordered[:, index]
        return result


@dataclass(slots=True)
class BlendBenchmarkResult:
    weekly_metrics: pd.DataFrame
    aggregate_metrics: pd.DataFrame
    diagnostics: dict[str, object]


def expanding_quantile_blend_benchmark(
    direct: pd.DataFrame,
    generative: pd.DataFrame,
    actuals: pd.DataFrame,
    *,
    test_seasons: tuple[int, ...] | list[int],
    week_start: int = 1,
    week_end: int = 18,
    min_history_rows: int = 200,
    min_position_rows: int = 100,
) -> BlendBenchmarkResult:
    aligned = align_projection_frames(direct, generative, actuals)
    if aligned.empty:
        raise ValueError("No aligned direct, generative, and actual projection rows")
    chronology = _chronology(aligned)
    rows: list[dict[str, float | int]] = []

    for season in sorted({int(value) for value in test_seasons}):
        for week in range(int(week_start), int(week_end) + 1):
            split = season * 25 + week
            train = aligned.loc[chronology < split]
            test = aligned.loc[
                (pd.to_numeric(aligned["season"], errors="coerce") == season)
                & (pd.to_numeric(aligned["week"], errors="coerce") == week)
            ]
            if len(train) < int(min_history_rows) or test.empty:
                continue
            calibrator = QuantileBlendCalibrator(min_position_rows=int(min_position_rows)).fit(train)
            blended = calibrator.transform(test)
            direct_metrics = _evaluate(blended, "direct")
            generative_metrics = _evaluate(blended, "generative")
            blend_metrics = _evaluate(blended, "blend")
            row: dict[str, float | int] = {
                "season": season,
                "week": week,
                "rows": int(blend_metrics["rows"]),
                "global_direct_weight": float(calibrator.global_direct_weight),
                "position_weights": int(len(calibrator.position_direct_weights)),
            }
            for name, metrics in (
                ("direct", direct_metrics),
                ("generative", generative_metrics),
                ("blend", blend_metrics),
            ):
                for metric, value in metrics.items():
                    if metric != "rows":
                        row[f"{name}_{metric}"] = float(value)
            row["blend_beats_direct"] = float(
                blend_metrics["pinball_loss"] < direct_metrics["pinball_loss"]
            )
            row["blend_beats_generative"] = float(
                blend_metrics["pinball_loss"] < generative_metrics["pinball_loss"]
            )
            row["blend_beats_best_component"] = float(
                blend_metrics["pinball_loss"]
                < min(direct_metrics["pinball_loss"], generative_metrics["pinball_loss"])
            )
            rows.append(row)

    weekly = pd.DataFrame(rows)
    if weekly.empty:
        raise ValueError("Blend benchmark produced no expanding-window folds")
    weights = pd.to_numeric(weekly["rows"], errors="coerce").fillna(1.0).clip(lower=1.0)
    aggregate_rows: list[dict[str, object]] = []
    for model in ("direct", "generative", "blend"):
        record: dict[str, object] = {"model": model, "rows": int(weights.sum())}
        for metric in ("pinball_loss", "median_mae", "q10_q90_coverage", "interval_width"):
            column = f"{model}_{metric}"
            values = pd.to_numeric(weekly[column], errors="coerce")
            valid = values.notna()
            if valid.any():
                record[metric] = float(np.average(values.loc[valid], weights=weights.loc[valid]))
        aggregate_rows.append(record)
    aggregate = pd.DataFrame(aggregate_rows)
    diagnostics = {
        "protocol": "expanding_quantile_blend_v011",
        "test_seasons": sorted({int(value) for value in test_seasons}),
        "folds": int(len(weekly)),
        "rows": int(weights.sum()),
        "blend_beats_best_component_fold_rate": float(weekly["blend_beats_best_component"].mean()),
        "blend_beats_direct_fold_rate": float(weekly["blend_beats_direct"].mean()),
        "blend_beats_generative_fold_rate": float(weekly["blend_beats_generative"].mean()),
        "promotion_boundary": "research_only; learned weights may not change production projections",
    }
    return BlendBenchmarkResult(weekly_metrics=weekly, aggregate_metrics=aggregate, diagnostics=diagnostics)
