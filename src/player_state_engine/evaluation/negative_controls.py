from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from player_state_engine.state_graph.experiments import PairedEffect, paired_block_bootstrap


@dataclass(slots=True, frozen=True)
class NegativeControlResult:
    method: str
    control_method: str
    rows: int
    singleton_groups: int
    groups: int
    real_mean_pinball: float
    control_mean_pinball: float
    effect_control_minus_real: float
    ci_low: float
    ci_high: float
    probability_real_improves: float
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _pinball(actual: pd.Series, prediction: pd.Series, quantile: float) -> pd.Series:
    residual = actual - prediction
    return pd.Series(
        np.maximum(quantile * residual, (quantile - 1.0) * residual),
        index=actual.index,
    )


def _row_pinball(frame: pd.DataFrame) -> pd.Series:
    actual = pd.to_numeric(frame["actual"], errors="coerce")
    q10 = pd.to_numeric(frame["q10"], errors="coerce")
    q50 = pd.to_numeric(frame["q50"], errors="coerce")
    q90 = pd.to_numeric(frame["q90"], errors="coerce")
    return (
        _pinball(actual, q10, 0.10)
        + _pinball(actual, q50, 0.50)
        + _pinball(actual, q90, 0.90)
    ) / 3.0


def identity_permutation_control(
    predictions: pd.DataFrame,
    *,
    method: str,
    target: str,
    seed: int = 42,
    group_columns: tuple[str, ...] = ("season", "position"),
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Destroy player identity while preserving coarse forecast marginals.

    Within each season/position slice, q10/q50/q90 triplets are cyclically shifted by a
    deterministic non-zero offset. This preserves the challenger's marginal distribution and
    quantile geometry while breaking the mapping from a player's state to that player's outcome.
    Singleton groups cannot be permuted and are reported explicitly.
    """

    required = {
        "target",
        "method",
        "player_id",
        "season",
        "week",
        "position",
        "actual",
        "q10",
        "q50",
        "q90",
    }
    missing = required - set(predictions)
    if missing:
        raise ValueError(f"Negative control missing canonical columns: {sorted(missing)}")

    data = predictions.loc[
        predictions["target"].astype(str).eq(str(target))
        & predictions["method"].astype(str).eq(str(method))
    ].copy()
    if "valid_prediction" in data:
        data = data.loc[data["valid_prediction"].astype(bool)].copy()
    if data.empty:
        raise ValueError(f"No valid rows for negative control method {method!r}")

    rng = np.random.default_rng(seed)
    control = data.copy()
    groups = 0
    singleton_groups = 0
    for _key, index in data.groupby(list(group_columns), dropna=False, sort=True).groups.items():
        groups += 1
        positions = np.asarray(list(index), dtype=int)
        if len(positions) <= 1:
            singleton_groups += 1
            continue
        shift = int(rng.integers(1, len(positions)))
        source_positions = np.roll(positions, shift)
        control.loc[positions, ["q10", "q50", "q90"]] = data.loc[
            source_positions, ["q10", "q50", "q90"]
        ].to_numpy()

    control_method = f"{method}__identity_permutation_control"
    control["method"] = control_method
    control["source"] = "negative_control_identity_permutation"
    if "forecast_id" in control:
        control["forecast_id"] = (
            control["target"].astype(str)
            + "|"
            + control["method"].astype(str)
            + "|"
            + control["player_id"].astype(str)
            + "|"
            + control["season"].astype("Int64").astype(str)
            + "|"
            + control["week"].astype("Int64").astype(str)
        )
    control["crossed_quantiles"] = (control["q10"] > control["q50"]) | (
        control["q50"] > control["q90"]
    )
    return control.reset_index(drop=True), {
        "groups": groups,
        "singleton_groups": singleton_groups,
    }


def evaluate_identity_permutation_control(
    real_predictions: pd.DataFrame,
    control_predictions: pd.DataFrame,
    *,
    method: str,
    target: str,
    bootstrap_samples: int = 2000,
    seed: int = 42,
    singleton_groups: int = 0,
    groups: int = 0,
) -> NegativeControlResult:
    """Require real forecasts to beat their identity-destroyed control with positive CI."""

    keys = ["target", "player_id", "season", "week"]
    real = real_predictions.loc[
        real_predictions["target"].astype(str).eq(str(target))
        & real_predictions["method"].astype(str).eq(str(method))
    ].copy()
    if "valid_prediction" in real:
        real = real.loc[real["valid_prediction"].astype(bool)].copy()
    control_method = f"{method}__identity_permutation_control"
    control = control_predictions.loc[
        control_predictions["target"].astype(str).eq(str(target))
        & control_predictions["method"].astype(str).eq(control_method)
    ].copy()
    if real.empty or control.empty:
        raise ValueError("Negative control requires both real and control rows")

    real["real_pinball"] = _row_pinball(real)
    control["control_pinball"] = _row_pinball(control)
    paired = real[keys + ["real_pinball"]].merge(
        control[keys + ["control_pinball"]],
        on=keys,
        how="inner",
        validate="one_to_one",
    )
    if paired.empty:
        raise ValueError("Negative control produced no paired observations")

    bootstrap: PairedEffect | None = None
    try:
        bootstrap = paired_block_bootstrap(
            paired,
            champion_column="control_pinball",
            challenger_column="real_pinball",
            bootstrap_samples=bootstrap_samples,
            seed=seed,
        )
    except ValueError:
        pass

    point_effect = float((paired["control_pinball"] - paired["real_pinball"]).mean())
    effect = point_effect if bootstrap is None else bootstrap.effect
    ci_low = float("nan") if bootstrap is None else bootstrap.ci_low
    ci_high = float("nan") if bootstrap is None else bootstrap.ci_high
    probability = (
        float("nan") if bootstrap is None else float(bootstrap.probability_improves)
    )
    passed = bool(np.isfinite(ci_low) and ci_low > 0.0 and effect > 0.0)
    return NegativeControlResult(
        method=method,
        control_method=control_method,
        rows=int(len(paired)),
        singleton_groups=int(singleton_groups),
        groups=int(groups),
        real_mean_pinball=float(paired["real_pinball"].mean()),
        control_mean_pinball=float(paired["control_pinball"].mean()),
        effect_control_minus_real=effect,
        ci_low=ci_low,
        ci_high=ci_high,
        probability_real_improves=probability,
        passed=passed,
    )
