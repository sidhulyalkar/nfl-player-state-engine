from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from player_state_engine.config import ModelConfig
from player_state_engine.evaluation.calibration import (
    interval_calibration_table,
    quantile_calibration_table,
)
from player_state_engine.evaluation.metrics import evaluate_quantiles
from player_state_engine.models.baselines import (
    position_prior_quantile_baseline,
    rolling_quantile_baseline,
)
from player_state_engine.models.hybrid import HybridQuantileModelBundle
from player_state_engine.models.quantile import TARGET_POSITIONS, QuantileModelBundle


@dataclass(slots=True)
class BenchmarkResult:
    predictions: pd.DataFrame
    fold_metrics: pd.DataFrame
    summary_metrics: pd.DataFrame
    season_metrics: pd.DataFrame
    position_metrics: pd.DataFrame
    quantile_calibration: pd.DataFrame
    interval_calibration: pd.DataFrame


def _metric_rows(
    predictions: pd.DataFrame,
    target: str,
    quantiles: tuple[float, ...],
    group_columns: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for key, subset in predictions.groupby(group_columns, dropna=False):
        key_tuple = key if isinstance(key, tuple) else (key,)
        row = dict(zip(group_columns, key_tuple, strict=False))
        pred_cols = subset[
            [column for column in subset.columns if column.startswith(f"{target}_q")]
        ]
        row.update(evaluate_quantiles(subset["actual"], pred_cols, target, quantiles))
        row["rows"] = len(subset)
        rows.append(row)
    return pd.DataFrame(rows)


def run_multiseason_benchmark(
    frame: pd.DataFrame,
    features: Iterable[str],
    target: str,
    config: ModelConfig | None = None,
    min_train_weeks: int = 24,
    retrain_every_weeks: int = 4,
    rolling_window: int = 5,
    engine_strategy: Literal["hybrid", "pooled"] = "hybrid",
) -> BenchmarkResult:
    """Compare the quantile engine with two transparent temporal baselines."""

    config = config or ModelConfig(targets=(target,))
    feature_list = list(features)
    actual_mask = (
        ~frame["is_projection_row"].astype(bool)
        if "is_projection_row" in frame
        else pd.Series(True, index=frame.index)
    )
    data = frame.loc[actual_mask].copy()
    if "player_history_count" in data:
        data = data.loc[data["player_history_count"] >= 1]
    eligible = TARGET_POSITIONS.get(target)
    if eligible and "position" in data:
        data = data.loc[data["position"].isin(eligible)]
    data = data.dropna(subset=[target]).copy()
    data["fold_week"] = data["season"] * 25 + data["week"]
    weeks = sorted(data["fold_week"].unique())
    if len(weeks) <= min_train_weeks:
        raise ValueError("Not enough unique weeks for the requested benchmark.")

    prediction_parts: list[pd.DataFrame] = []
    fold_metric_rows: list[dict[str, object]] = []
    engine: QuantileModelBundle | HybridQuantileModelBundle | None = None

    for fold_index, test_week in enumerate(weeks[min_train_weeks:]):
        train = data.loc[data["fold_week"] < test_week]
        test = data.loc[data["fold_week"] == test_week].copy()
        if test.empty:
            continue
        if engine is None or fold_index % retrain_every_weeks == 0:
            if engine_strategy == "hybrid":
                engine = HybridQuantileModelBundle(config=config).fit(
                    train, feature_list, targets=(target,)
                )
            else:
                engine = QuantileModelBundle(config=config).fit(
                    train, feature_list, targets=(target,)
                )

        methods = {
            "quantile_engine": engine.predict(test),
            f"rolling_{rolling_window}": rolling_quantile_baseline(
                train, test, target, config.quantiles, window=rolling_window
            ),
            "position_prior": position_prior_quantile_baseline(
                train, test, target, config.quantiles
            ),
        }
        for method, predicted in methods.items():
            predicted = predicted.reset_index(drop=True)
            predicted["actual"] = test[target].to_numpy(dtype=float)
            predicted["fold_week"] = int(test_week)
            predicted["method"] = method
            prediction_parts.append(predicted)
            metrics = evaluate_quantiles(test[target], predicted, target, config.quantiles)
            fold_metric_rows.append(
                {
                    "method": method,
                    "fold_week": int(test_week),
                    "season": int(test["season"].iloc[0]),
                    "week": int(test["week"].iloc[0]),
                    "rows": len(test),
                    **metrics,
                }
            )

    predictions = pd.concat(prediction_parts, ignore_index=True)
    summary = _metric_rows(predictions, target, config.quantiles, ["method"])
    season = _metric_rows(predictions, target, config.quantiles, ["method", "season"])
    position = _metric_rows(predictions, target, config.quantiles, ["method", "position"])
    quantile_calibration = quantile_calibration_table(
        predictions, target, config.quantiles, group_columns=("method", "position")
    )
    interval_calibration = interval_calibration_table(
        predictions,
        target,
        lower_quantile=min(config.quantiles),
        upper_quantile=max(config.quantiles),
        group_columns=("method", "position"),
    )
    return BenchmarkResult(
        predictions=predictions,
        fold_metrics=pd.DataFrame(fold_metric_rows),
        summary_metrics=summary,
        season_metrics=season,
        position_metrics=position,
        quantile_calibration=quantile_calibration,
        interval_calibration=interval_calibration,
    )


def write_benchmark_markdown(result: BenchmarkResult, target: str, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = result.summary_metrics.sort_values("mean_pinball")
    season = result.season_metrics.sort_values(["season", "mean_pinball"])
    position = result.position_metrics.sort_values(["position", "mean_pinball"])
    calibration = (
        result.quantile_calibration.groupby("method", as_index=False)["absolute_calibration_error"]
        .mean()
        .rename(columns={"absolute_calibration_error": "mean_absolute_calibration_error"})
        .sort_values("mean_absolute_calibration_error")
    )
    text = [
        f"# Multi-season benchmark: `{target}`",
        "",
        "All rows are walk-forward out-of-sample predictions. Lower MAE, RMSE, pinball loss, and calibration error are better.",
        "",
        "## Overall comparison",
        "",
        summary.to_markdown(index=False),
        "",
        "## Held-out season comparison",
        "",
        season.to_markdown(index=False),
        "",
        "## Position-specific comparison",
        "",
        position.to_markdown(index=False),
        "",
        "## Quantile calibration summary",
        "",
        calibration.to_markdown(index=False),
        "",
        "## Promotion gate",
        "",
        "Do not add news, persona, tracking, or deeper sequence models until the quantile engine demonstrates a stable improvement over both baselines across multiple held-out seasons and its intervals are acceptably calibrated by position.",
        "",
    ]
    path.write_text("\n".join(text), encoding="utf-8")
    return path
