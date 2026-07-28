from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd


def quantile_calibration_table(
    predictions: pd.DataFrame,
    target: str,
    quantiles: Iterable[float] = (0.1, 0.5, 0.9),
    group_columns: Sequence[str] = ("method", "position"),
) -> pd.DataFrame:
    """Measure whether observed values fall below each predicted quantile at the nominal rate."""

    qs = tuple(sorted(float(q) for q in quantiles))
    groups = [column for column in group_columns if column in predictions.columns]
    iterator = predictions.groupby(groups, dropna=False) if groups else [((), predictions)]
    rows: list[dict[str, object]] = []
    for key, subset in iterator:
        key_tuple = key if isinstance(key, tuple) else (key,)
        base = dict(zip(groups, key_tuple, strict=False))
        actual = pd.to_numeric(subset["actual"], errors="coerce").to_numpy(dtype=float)
        for quantile in qs:
            column = f"{target}_q{int(round(quantile * 100)):02d}"
            predicted = pd.to_numeric(subset[column], errors="coerce").to_numpy(dtype=float)
            valid = np.isfinite(actual) & np.isfinite(predicted)
            empirical = (
                float(np.mean(actual[valid] <= predicted[valid])) if valid.any() else float("nan")
            )
            rows.append(
                {
                    **base,
                    "target": target,
                    "quantile": quantile,
                    "rows": int(valid.sum()),
                    "empirical_rate": empirical,
                    "calibration_error": empirical - quantile,
                    "absolute_calibration_error": abs(empirical - quantile),
                }
            )
    return pd.DataFrame(rows)


def interval_calibration_table(
    predictions: pd.DataFrame,
    target: str,
    lower_quantile: float = 0.1,
    upper_quantile: float = 0.9,
    group_columns: Sequence[str] = ("method", "position"),
) -> pd.DataFrame:
    groups = [column for column in group_columns if column in predictions.columns]
    iterator = predictions.groupby(groups, dropna=False) if groups else [((), predictions)]
    low_col = f"{target}_q{int(round(lower_quantile * 100)):02d}"
    high_col = f"{target}_q{int(round(upper_quantile * 100)):02d}"
    nominal = upper_quantile - lower_quantile
    rows: list[dict[str, object]] = []
    for key, subset in iterator:
        key_tuple = key if isinstance(key, tuple) else (key,)
        base = dict(zip(groups, key_tuple, strict=False))
        actual = pd.to_numeric(subset["actual"], errors="coerce").to_numpy(dtype=float)
        lower = pd.to_numeric(subset[low_col], errors="coerce").to_numpy(dtype=float)
        upper = pd.to_numeric(subset[high_col], errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(actual) & np.isfinite(lower) & np.isfinite(upper)
        coverage = (
            float(np.mean((actual[valid] >= lower[valid]) & (actual[valid] <= upper[valid])))
            if valid.any()
            else float("nan")
        )
        width = float(np.mean(upper[valid] - lower[valid])) if valid.any() else float("nan")
        rows.append(
            {
                **base,
                "target": target,
                "rows": int(valid.sum()),
                "nominal_coverage": nominal,
                "empirical_coverage": coverage,
                "coverage_error": coverage - nominal,
                "mean_interval_width": width,
            }
        )
    return pd.DataFrame(rows)
