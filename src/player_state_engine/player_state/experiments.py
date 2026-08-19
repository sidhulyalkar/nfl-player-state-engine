from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import Sequence

import numpy as np
import pandas as pd


class EvidenceTier(IntEnum):
    SYNTHETIC_ONLY = 0
    SINGLE_HISTORICAL_SLICE = 1
    MULTI_SEASON_ISOLATED = 2
    MULTI_SEASON_DOWNSTREAM = 3
    LIVE_SHADOW_SEASON = 4
    DECISION_VALUE_VALIDATED = 5


@dataclass(frozen=True, slots=True)
class PairedEffectEstimate:
    effect: float
    ci_low: float
    ci_high: float
    probability_improves: float
    blocks: int
    rows: int
    metric: str
    lower_is_better: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ExperimentEvidence:
    experiment_id: str
    evidence_tier: EvidenceTier
    primary_metric: str
    effect: PairedEffectEstimate
    season_consistency: float | None
    position_consistency: float | None
    coverage: float | None
    source_availability: float | None
    negative_control_passed: bool
    downstream_decision_passed: bool | None
    preregistered: bool
    minimum_useful_effect: float

    @property
    def promotion_eligible(self) -> bool:
        directional_effect = (
            -self.effect.effect if self.effect.lower_is_better else self.effect.effect
        )
        directional_ci = (
            -self.effect.ci_high if self.effect.lower_is_better else self.effect.ci_low
        )
        return bool(
            self.preregistered
            and self.evidence_tier >= EvidenceTier.MULTI_SEASON_ISOLATED
            and self.negative_control_passed
            and directional_effect >= self.minimum_useful_effect
            and directional_ci > 0.0
            and (self.downstream_decision_passed is not False)
        )

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["evidence_tier"] = int(self.evidence_tier)
        payload["promotion_eligible"] = self.promotion_eligible
        return payload


def paired_block_bootstrap(
    frame: pd.DataFrame,
    *,
    candidate_column: str,
    reference_column: str,
    metric: str,
    block_columns: Sequence[str] = ("season", "week"),
    lower_is_better: bool = True,
    samples: int = 2000,
    seed: int = 42,
) -> PairedEffectEstimate:
    """Paired block bootstrap for forecasts evaluated on identical player-weeks.

    The returned effect is candidate minus reference. For a loss metric, negative is better.
    Blocks default to season/week to avoid pretending player rows from one NFL week are
    independent observations.
    """

    required = {candidate_column, reference_column, *block_columns}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"bootstrap frame missing columns: {sorted(missing)}")
    work = frame.copy()
    candidate = pd.to_numeric(work[candidate_column], errors="coerce")
    reference = pd.to_numeric(work[reference_column], errors="coerce")
    valid = candidate.notna() & reference.notna()
    work = work.loc[valid].copy()
    work["_difference"] = candidate.loc[valid].to_numpy(float) - reference.loc[valid].to_numpy(float)
    if work.empty:
        raise ValueError("No paired finite rows remain")
    block_means = (
        work.groupby(list(block_columns), dropna=False)["_difference"].mean().to_numpy(float)
    )
    if not len(block_means):
        raise ValueError("No bootstrap blocks remain")
    rng = np.random.default_rng(seed)
    samples = max(int(samples), 200)
    draws = rng.choice(block_means, size=(samples, len(block_means)), replace=True).mean(axis=1)
    effect = float(work["_difference"].mean())
    low, high = np.quantile(draws, [0.025, 0.975])
    improves = draws < 0.0 if lower_is_better else draws > 0.0
    return PairedEffectEstimate(
        effect=effect,
        ci_low=float(low),
        ci_high=float(high),
        probability_improves=float(np.mean(improves)),
        blocks=len(block_means),
        rows=len(work),
        metric=str(metric),
        lower_is_better=bool(lower_is_better),
    )


def consistency_rate(
    frame: pd.DataFrame,
    *,
    candidate_column: str,
    reference_column: str,
    group_column: str,
    lower_is_better: bool = True,
) -> float:
    """Fraction of seasons/positions where the candidate moves in the desired direction."""

    required = {candidate_column, reference_column, group_column}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"consistency frame missing columns: {sorted(missing)}")
    grouped = frame.groupby(group_column, dropna=False)[[candidate_column, reference_column]].mean()
    if grouped.empty:
        return float("nan")
    delta = grouped[candidate_column] - grouped[reference_column]
    return float(np.mean(delta < 0.0 if lower_is_better else delta > 0.0))


def benjamini_hochberg(p_values: Sequence[float], *, alpha: float = 0.05) -> np.ndarray:
    """Return a boolean FDR discovery mask in the original p-value order."""

    values = np.asarray(p_values, dtype=float)
    if values.ndim != 1:
        raise ValueError("p_values must be one-dimensional")
    if len(values) == 0:
        return np.zeros(0, dtype=bool)
    if np.any(~np.isfinite(values)) or np.any((values < 0.0) | (values > 1.0)):
        raise ValueError("p_values must be finite and between 0 and 1")
    order = np.argsort(values)
    ranked = values[order]
    thresholds = float(alpha) * np.arange(1, len(values) + 1) / len(values)
    passing = np.where(ranked <= thresholds)[0]
    mask = np.zeros(len(values), dtype=bool)
    if len(passing):
        cutoff = ranked[passing[-1]]
        mask = values <= cutoff
    return mask
