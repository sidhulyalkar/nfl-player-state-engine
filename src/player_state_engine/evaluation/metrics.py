from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_pinball_loss, mean_squared_error


def evaluate_quantiles(
    truth: pd.Series | np.ndarray,
    predictions: pd.DataFrame,
    target: str,
    quantiles: Iterable[float] = (0.1, 0.5, 0.9),
) -> dict[str, float]:
    y = np.asarray(truth, dtype=float)
    result: dict[str, float] = {}
    quantiles = tuple(sorted(float(q) for q in quantiles))
    for quantile in quantiles:
        column = f"{target}_q{int(round(quantile * 100)):02d}"
        pred = predictions[column].to_numpy(dtype=float)
        result[f"pinball_q{int(quantile * 100):02d}"] = float(
            mean_pinball_loss(y, pred, alpha=quantile)
        )
        if abs(quantile - 0.5) < 1e-9:
            result["mae"] = float(mean_absolute_error(y, pred))
            result["rmse"] = float(mean_squared_error(y, pred) ** 0.5)
            result["bias"] = float(np.mean(pred - y))

    if len(quantiles) >= 2:
        low, high = quantiles[0], quantiles[-1]
        low_col = f"{target}_q{int(round(low * 100)):02d}"
        high_col = f"{target}_q{int(round(high * 100)):02d}"
        lower = predictions[low_col].to_numpy(dtype=float)
        upper = predictions[high_col].to_numpy(dtype=float)
        result["interval_coverage"] = float(np.mean((y >= lower) & (y <= upper)))
        result["mean_interval_width"] = float(np.mean(upper - lower))

    pinballs = [value for key, value in result.items() if key.startswith("pinball_")]
    if pinballs:
        result["mean_pinball"] = float(np.mean(pinballs))
    return result


def grouped_metrics(
    frame: pd.DataFrame,
    predictions: pd.DataFrame,
    target: str,
    group_column: str = "position",
) -> pd.DataFrame:
    joined = frame.reset_index(drop=True).copy()
    for column in predictions.columns:
        if column.startswith(f"{target}_q"):
            joined[column] = predictions[column].to_numpy()
    rows: list[dict[str, object]] = []
    for group, subset in joined.groupby(group_column, dropna=False):
        pred_cols = subset[[c for c in subset.columns if c.startswith(f"{target}_q")]]
        row: dict[str, object] = {group_column: group, "rows": len(subset)}
        row.update(evaluate_quantiles(subset[target], pred_cols, target))
        rows.append(row)
    return pd.DataFrame(rows)
