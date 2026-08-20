from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from player_state_engine.player_state.experiments import (
    PairedEffectEstimate,
    consistency_rate,
    paired_block_bootstrap,
)


@dataclass(frozen=True, slots=True)
class ForecastScorecard:
    model: str
    rows: int
    median_mae: float
    mean_pinball: float
    interval_coverage: float
    interval_width: float
    weighted_interval_score: float
    q10_empirical: float
    q50_empirical: float
    q90_empirical: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ForecastComparison:
    candidate: str
    reference: str
    wis_effect: PairedEffectEstimate
    season_consistency: float | None
    position_consistency: float | None
    coverage_delta: float
    width_delta: float

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate,
            "reference": self.reference,
            "wis_effect": self.wis_effect.as_dict(),
            "season_consistency": self.season_consistency,
            "position_consistency": self.position_consistency,
            "coverage_delta": self.coverage_delta,
            "width_delta": self.width_delta,
        }


def _pinball_loss(actual: np.ndarray, prediction: np.ndarray, quantile: float) -> np.ndarray:
    error = actual - prediction
    return np.maximum(quantile * error, (quantile - 1.0) * error)


def _interval_score(
    actual: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    *,
    alpha: float,
) -> np.ndarray:
    width = np.maximum(upper - lower, 0.0)
    below = np.maximum(lower - actual, 0.0)
    above = np.maximum(actual - upper, 0.0)
    return width + (2.0 / alpha) * below + (2.0 / alpha) * above


def _wis(
    actual: np.ndarray,
    q10: np.ndarray,
    q50: np.ndarray,
    q90: np.ndarray,
) -> np.ndarray:
    """Standard WIS for one central 80% interval plus its median.

    With one interval (K=1), the standard WIS normalization is K + 1/2 = 1.5,
    with weights 1/2 for absolute median error and alpha/2 for interval score.
    """

    alpha = 0.20
    median_component = 0.5 * np.abs(actual - q50)
    interval_component = (alpha / 2.0) * _interval_score(actual, q10, q90, alpha=alpha)
    return (median_component + interval_component) / 1.5


def _forecast_columns(model: str) -> tuple[str, str, str]:
    return f"{model}_q10", f"{model}_q50", f"{model}_q90"


def forecast_loss_frame(
    frame: pd.DataFrame,
    *,
    model: str,
    actual_column: str = "actual",
) -> pd.DataFrame:
    """Return row-level proper losses so every comparison remains paired."""

    q10_column, q50_column, q90_column = _forecast_columns(model)
    required = {actual_column, q10_column, q50_column, q90_column}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"forecast benchmark missing columns: {sorted(missing)}")
    out = frame.copy()
    for column in required:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=list(required)).copy()
    if out.empty:
        raise ValueError("no finite forecast rows remain")

    actual = out[actual_column].to_numpy(float)
    q10 = out[q10_column].to_numpy(float)
    q50 = out[q50_column].to_numpy(float)
    q90 = out[q90_column].to_numpy(float)
    quantiles = np.sort(np.column_stack([q10, q50, q90]), axis=1)
    q10, q50, q90 = quantiles[:, 0], quantiles[:, 1], quantiles[:, 2]

    out[f"{model}_median_absolute_error"] = np.abs(actual - q50)
    out[f"{model}_mean_pinball"] = (
        _pinball_loss(actual, q10, 0.10)
        + _pinball_loss(actual, q50, 0.50)
        + _pinball_loss(actual, q90, 0.90)
    ) / 3.0
    out[f"{model}_wis"] = _wis(actual, q10, q50, q90)
    out[f"{model}_covered"] = ((actual >= q10) & (actual <= q90)).astype(float)
    out[f"{model}_interval_width"] = q90 - q10
    out[f"{model}_q10_hit"] = (actual <= q10).astype(float)
    out[f"{model}_q50_hit"] = (actual <= q50).astype(float)
    out[f"{model}_q90_hit"] = (actual <= q90).astype(float)
    return out


def evaluate_forecast(
    frame: pd.DataFrame,
    *,
    model: str,
    actual_column: str = "actual",
) -> ForecastScorecard:
    losses = forecast_loss_frame(frame, model=model, actual_column=actual_column)
    return ForecastScorecard(
        model=str(model),
        rows=len(losses),
        median_mae=float(losses[f"{model}_median_absolute_error"].mean()),
        mean_pinball=float(losses[f"{model}_mean_pinball"].mean()),
        interval_coverage=float(losses[f"{model}_covered"].mean()),
        interval_width=float(losses[f"{model}_interval_width"].mean()),
        weighted_interval_score=float(losses[f"{model}_wis"].mean()),
        q10_empirical=float(losses[f"{model}_q10_hit"].mean()),
        q50_empirical=float(losses[f"{model}_q50_hit"].mean()),
        q90_empirical=float(losses[f"{model}_q90_hit"].mean()),
    )


def compare_forecasts(
    frame: pd.DataFrame,
    *,
    candidate: str,
    reference: str,
    actual_column: str = "actual",
    block_columns: tuple[str, ...] = ("season", "week"),
    bootstrap_samples: int = 3000,
    seed: int = 42,
) -> ForecastComparison:
    """Compare probabilistic forecasts on identical rows with WIS as primary loss."""

    candidate_loss = forecast_loss_frame(frame, model=candidate, actual_column=actual_column)
    reference_loss = forecast_loss_frame(frame, model=reference, actual_column=actual_column)
    identity_columns = [
        column
        for column in (
            "season",
            "week",
            "player_id",
            "position",
            "target",
            "forecast_horizon",
        )
        if column in frame
    ]
    if not identity_columns:
        candidate_loss = candidate_loss.reset_index().rename(columns={"index": "_row_id"})
        reference_loss = reference_loss.reset_index().rename(columns={"index": "_row_id"})
        identity_columns = ["_row_id"]
    paired = candidate_loss[
        [
            *identity_columns,
            f"{candidate}_wis",
            f"{candidate}_covered",
            f"{candidate}_interval_width",
        ]
    ].merge(
        reference_loss[
            [
                *identity_columns,
                f"{reference}_wis",
                f"{reference}_covered",
                f"{reference}_interval_width",
            ]
        ],
        on=identity_columns,
        how="inner",
        validate="one_to_one",
    )
    if paired.empty:
        raise ValueError("no paired forecast rows remain")

    usable_blocks = tuple(column for column in block_columns if column in paired)
    bootstrap_blocks = usable_blocks if usable_blocks else tuple(identity_columns[:1])
    effect = paired_block_bootstrap(
        paired,
        candidate_column=f"{candidate}_wis",
        reference_column=f"{reference}_wis",
        metric="weighted_interval_score",
        block_columns=bootstrap_blocks,
        lower_is_better=True,
        samples=bootstrap_samples,
        seed=seed,
    )
    season_consistency = (
        consistency_rate(
            paired,
            candidate_column=f"{candidate}_wis",
            reference_column=f"{reference}_wis",
            group_column="season",
            lower_is_better=True,
        )
        if "season" in paired
        else None
    )
    position_consistency = (
        consistency_rate(
            paired,
            candidate_column=f"{candidate}_wis",
            reference_column=f"{reference}_wis",
            group_column="position",
            lower_is_better=True,
        )
        if "position" in paired
        else None
    )
    return ForecastComparison(
        candidate=str(candidate),
        reference=str(reference),
        wis_effect=effect,
        season_consistency=season_consistency,
        position_consistency=position_consistency,
        coverage_delta=float(
            paired[f"{candidate}_covered"].mean() - paired[f"{reference}_covered"].mean()
        ),
        width_delta=float(
            paired[f"{candidate}_interval_width"].mean()
            - paired[f"{reference}_interval_width"].mean()
        ),
    )


def grouped_forecast_scorecards(
    frame: pd.DataFrame,
    *,
    models: tuple[str, ...],
    actual_column: str = "actual",
    group_columns: tuple[str, ...] = ("season", "position", "target"),
    minimum_rows: int = 30,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for model in models:
        rows.append(
            {
                "group": "overall",
                "value": "all",
                **evaluate_forecast(
                    frame, model=model, actual_column=actual_column
                ).as_dict(),
            }
        )
        for group_column in group_columns:
            if group_column not in frame:
                continue
            for value, group in frame.groupby(group_column, dropna=False):
                if len(group) < int(minimum_rows):
                    continue
                try:
                    scorecard = evaluate_forecast(group, model=model, actual_column=actual_column)
                except ValueError:
                    continue
                rows.append(
                    {
                        "group": str(group_column),
                        "value": str(value),
                        **scorecard.as_dict(),
                    }
                )
    return pd.DataFrame(rows)
