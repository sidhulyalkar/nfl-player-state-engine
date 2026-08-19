from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Iterable

import numpy as np
import pandas as pd


class EvidenceTier(IntEnum):
    SYNTHETIC_ONLY = 0
    SINGLE_HISTORICAL_SLICE = 1
    MULTI_SEASON_ISOLATED = 2
    MULTI_SEASON_DOWNSTREAM = 3
    LIVE_SHADOW_SEASON = 4
    DECISION_VALUE_VALIDATED = 5


@dataclass(slots=True, frozen=True)
class PairedEffect:
    effect: float
    ci_low: float
    ci_high: float
    probability_improves: float
    blocks: int
    bootstrap_samples: int


@dataclass(slots=True)
class ExperimentRecord:
    experiment_id: str
    challenger: str
    champion: str
    primary_metric: str
    evidence_tier: EvidenceTier
    effect: float
    ci_low: float
    ci_high: float
    season_consistency: float
    position_consistency: float
    week_consistency: float
    coverage: float
    data_availability: float
    negative_control_passed: bool
    downstream_decision_effect: float | None = None
    p_value: float | None = None
    fdr_q_value: float | None = None
    promoted: bool = False
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["evidence_tier"] = int(self.evidence_tier)
        return payload


def paired_block_bootstrap(
    frame: pd.DataFrame,
    *,
    champion_column: str,
    challenger_column: str,
    block_columns: tuple[str, ...] = ("season", "week"),
    lower_is_better: bool = True,
    bootstrap_samples: int = 2000,
    seed: int = 42,
) -> PairedEffect:
    missing = {champion_column, challenger_column, *block_columns} - set(frame)
    if missing:
        raise ValueError(f"Paired bootstrap missing columns: {sorted(missing)}")
    data = frame.dropna(subset=[champion_column, challenger_column, *block_columns]).copy()
    if data.empty:
        raise ValueError("No paired observations")
    champion = pd.to_numeric(data[champion_column], errors="coerce")
    challenger = pd.to_numeric(data[challenger_column], errors="coerce")
    if lower_is_better:
        data["_effect"] = champion - challenger
    else:
        data["_effect"] = challenger - champion
    data = data.loc[data["_effect"].notna()]
    grouped = data.groupby(list(block_columns), sort=False)["_effect"].mean()
    values = grouped.to_numpy(dtype=float)
    if len(values) < 2:
        raise ValueError("Paired block bootstrap requires at least two blocks")
    rng = np.random.default_rng(seed)
    samples = np.empty(max(200, int(bootstrap_samples)), dtype=float)
    for index in range(len(samples)):
        resampled = rng.choice(values, size=len(values), replace=True)
        samples[index] = float(np.mean(resampled))
    low, high = np.quantile(samples, [0.025, 0.975])
    return PairedEffect(
        effect=float(np.mean(values)),
        ci_low=float(low),
        ci_high=float(high),
        probability_improves=float(np.mean(samples > 0.0)),
        blocks=int(len(values)),
        bootstrap_samples=int(len(samples)),
    )


def consistency_rate(
    frame: pd.DataFrame,
    *,
    effect_column: str,
    group_columns: Iterable[str],
) -> float:
    columns = [column for column in group_columns if column in frame]
    if not columns:
        return float("nan")
    grouped = frame.groupby(columns, dropna=False)[effect_column].mean()
    if grouped.empty:
        return float("nan")
    return float(np.mean(grouped.to_numpy(dtype=float) > 0.0))


def benjamini_hochberg(p_values: dict[str, float]) -> dict[str, float]:
    valid = [(key, float(value)) for key, value in p_values.items() if np.isfinite(value)]
    valid.sort(key=lambda item: item[1])
    m = len(valid)
    if m == 0:
        return {}
    adjusted: dict[str, float] = {}
    running = 1.0
    for rank_from_end, (key, p_value) in enumerate(reversed(valid), start=1):
        rank = m - rank_from_end + 1
        q_value = min(running, p_value * m / rank)
        running = q_value
        adjusted[key] = float(min(1.0, q_value))
    return adjusted


@dataclass(slots=True)
class PromotionPolicy:
    """Fail-closed evidence authority gate."""

    minimum_tier: EvidenceTier = EvidenceTier.MULTI_SEASON_DOWNSTREAM
    minimum_effect: float = 0.0
    minimum_ci_low: float = 0.0
    minimum_consistency: float = 0.55
    minimum_coverage: float = 0.80
    minimum_data_availability: float = 0.80
    maximum_fdr_q: float = 0.10
    require_negative_control: bool = True

    def evaluate(self, record: ExperimentRecord) -> ExperimentRecord:
        blockers: list[str] = []
        if record.evidence_tier < self.minimum_tier:
            blockers.append(f"evidence_tier<{int(self.minimum_tier)}")
        if record.effect <= self.minimum_effect:
            blockers.append("effect_below_minimum_useful_effect")
        if record.ci_low <= self.minimum_ci_low:
            blockers.append("confidence_interval_crosses_gate")
        consistency_values = (
            record.season_consistency,
            record.position_consistency,
            record.week_consistency,
        )
        finite_consistency = [value for value in consistency_values if np.isfinite(value)]
        if finite_consistency and min(finite_consistency) < self.minimum_consistency:
            blockers.append("inconsistent_slice_effect")
        if record.coverage < self.minimum_coverage:
            blockers.append("insufficient_coverage")
        if record.data_availability < self.minimum_data_availability:
            blockers.append("insufficient_live_data_availability")
        if self.require_negative_control and not record.negative_control_passed:
            blockers.append("negative_control_failed")
        if record.fdr_q_value is not None and record.fdr_q_value > self.maximum_fdr_q:
            blockers.append("fdr_q_above_threshold")
        record.blockers = blockers
        record.promoted = not blockers
        return record


@dataclass(slots=True)
class ExperimentLedger:
    records: list[ExperimentRecord] = field(default_factory=list)

    def add(self, record: ExperimentRecord) -> None:
        existing = {item.experiment_id for item in self.records}
        if record.experiment_id in existing:
            raise ValueError(f"Duplicate experiment id: {record.experiment_id}")
        self.records.append(record)

    def apply_fdr(self) -> None:
        q_values = benjamini_hochberg(
            {
                record.experiment_id: record.p_value
                for record in self.records
                if record.p_value is not None
            }
        )
        for record in self.records:
            if record.experiment_id in q_values:
                record.fdr_q_value = q_values[record.experiment_id]

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([record.to_dict() for record in self.records])
