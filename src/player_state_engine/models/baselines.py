from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from player_state_engine.models.quantile import NONNEGATIVE_TARGETS


def rolling_mean_baseline(frame: pd.DataFrame, target: str, window: int = 5) -> pd.Series:
    """Return a precomputed, leakage-safe rolling point estimate.

    Feature construction shifts all rolling statistics by one game, so this
    function is safe only when called on a table produced by ``build_weekly_features``.
    """

    candidate = f"{target}_roll{window}_mean"
    if candidate in frame.columns:
        return pd.to_numeric(frame[candidate], errors="coerce").fillna(0.0)
    lag = f"{target}_lag1"
    if lag in frame.columns:
        return pd.to_numeric(frame[lag], errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=frame.index, dtype=float)


def _context(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        column
        for column in (
            "season",
            "week",
            "game_id",
            "player_id",
            "player_name",
            "recent_team",
            "opponent_team",
            "position",
        )
        if column in frame.columns
    ]
    return frame[columns].reset_index(drop=True).copy()


def _group_quantiles(
    frame: pd.DataFrame,
    values: pd.Series,
    quantiles: tuple[float, ...],
    group_column: str = "position",
) -> tuple[dict[object, dict[float, float]], dict[float, float]]:
    working = pd.DataFrame({group_column: frame[group_column], "value": values}, index=frame.index)
    working = working.replace([np.inf, -np.inf], np.nan).dropna(subset=["value"])
    global_values = working["value"]
    if global_values.empty:
        global_q = {q: 0.0 for q in quantiles}
    else:
        global_q = {q: float(global_values.quantile(q)) for q in quantiles}

    grouped: dict[object, dict[float, float]] = {}
    for group, subset in working.groupby(group_column, dropna=False):
        if len(subset) < 10:
            continue
        grouped[group] = {q: float(subset["value"].quantile(q)) for q in quantiles}
    return grouped, global_q


def _apply_monotonic_nonnegative(
    output: pd.DataFrame,
    target: str,
    quantiles: tuple[float, ...],
) -> pd.DataFrame:
    columns = [f"{target}_q{int(round(q * 100)):02d}" for q in quantiles]
    values = np.sort(output[columns].to_numpy(dtype=float), axis=1)
    if target in NONNEGATIVE_TARGETS:
        values = np.clip(values, 0.0, None)
    output[columns] = values
    return output


def rolling_quantile_baseline(
    train: pd.DataFrame,
    test: pd.DataFrame,
    target: str,
    quantiles: Iterable[float] = (0.1, 0.5, 0.9),
    window: int = 5,
) -> pd.DataFrame:
    """Rolling mean plus position-conditioned historical residual quantiles."""

    qs = tuple(sorted(float(q) for q in quantiles))
    train_point = rolling_mean_baseline(train, target, window=window)
    residual = pd.to_numeric(train[target], errors="coerce") - train_point
    grouped, global_q = _group_quantiles(train, residual, qs)

    test_point = rolling_mean_baseline(test, target, window=window).reset_index(drop=True)
    positions = (
        test["position"].reset_index(drop=True)
        if "position" in test
        else pd.Series("ALL", index=test_point.index)
    )
    output = _context(test)
    for q in qs:
        adjustment = positions.map(
            lambda value, quantile=q: grouped.get(value, global_q).get(quantile, global_q[quantile])
        ).astype(float)
        output[f"{target}_q{int(round(q * 100)):02d}"] = test_point + adjustment
    return _apply_monotonic_nonnegative(output, target, qs)


def position_prior_quantile_baseline(
    train: pd.DataFrame,
    test: pd.DataFrame,
    target: str,
    quantiles: Iterable[float] = (0.1, 0.5, 0.9),
) -> pd.DataFrame:
    """Use only the historical target distribution for the player's position."""

    qs = tuple(sorted(float(q) for q in quantiles))
    values = pd.to_numeric(train[target], errors="coerce")
    grouped, global_q = _group_quantiles(train, values, qs)
    positions = (
        test["position"].reset_index(drop=True)
        if "position" in test
        else pd.Series("ALL", index=test.index)
    )
    output = _context(test)
    for q in qs:
        output[f"{target}_q{int(round(q * 100)):02d}"] = positions.map(
            lambda value, quantile=q: grouped.get(value, global_q).get(quantile, global_q[quantile])
        ).astype(float)
    return _apply_monotonic_nonnegative(output, target, qs)
