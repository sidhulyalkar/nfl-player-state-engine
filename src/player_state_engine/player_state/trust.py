from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from player_state_engine.player_state.graph import PlayerStateSnapshot, UncertaintyBreakdown
from player_state_engine.player_state.insights import PlayerIntelligenceCard


@dataclass(frozen=True, slots=True)
class ForecastTrustReport:
    score: float
    grade: str
    action_policy: str
    flags: tuple[str, ...]
    evidence_age_hours: float | None
    relative_interval_width: float
    simulation_rows: int
    component_scores: Mapping[str, float]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bounded(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def assess_forecast_trust(
    snapshot: PlayerStateSnapshot,
    draws: pd.DataFrame,
    uncertainty: UncertaintyBreakdown,
    card: PlayerIntelligenceCard,
    *,
    as_of: datetime | None = None,
    max_evidence_age_hours: float = 72.0,
    minimum_simulations: int = 500,
) -> ForecastTrustReport:
    """Assess whether a forecast is safe to present with strong language.

    This is a presentation and decision guardrail, not a second predictive model. It combines
    evidence freshness, role-state maturity, distribution width, Monte Carlo support, and model
    disagreement into an explicit trust report. A low score does not mean the player is bad; it
    means the system should communicate the recommendation more cautiously.
    """

    if "league_fantasy_points" not in draws:
        raise ValueError("draws must contain league_fantasy_points")
    values = pd.to_numeric(draws["league_fantasy_points"], errors="coerce").dropna().to_numpy(float)
    if not len(values):
        raise ValueError("draws contain no finite league_fantasy_points")

    now = _utc(as_of or datetime.now(UTC))
    freshness_hours: float | None
    if card.evidence_freshness is None:
        freshness_hours = None
        freshness_score = 0.35
    else:
        evidence_time = _utc(card.evidence_freshness)
        freshness_hours = max(0.0, (now - evidence_time).total_seconds() / 3600.0)
        freshness_score = float(
            np.exp(-freshness_hours / max(float(max_evidence_age_hours), 1.0))
        )

    maturity_score = _bounded(float(snapshot.role.maturity))
    change_score = _bounded(1.0 - float(snapshot.role.role_change_probability))

    q10, q50, q90 = np.quantile(values, [0.10, 0.50, 0.90])
    interval_width = float(max(q90 - q10, 0.0))
    relative_width = interval_width / max(abs(float(q50)), 5.0)
    sharpness_score = _bounded(1.0 - relative_width / 2.5)

    simulation_rows = int(len(values))
    simulation_score = _bounded(simulation_rows / max(float(minimum_simulations), 1.0))

    disagreement = float(card.consensus_disagreement or 0.0)
    disagreement_scale = max(interval_width, 5.0)
    agreement_score = _bounded(1.0 - disagreement / disagreement_scale)

    variance_score = _bounded(1.0 - float(uncertainty.total_variance) / 250.0)

    component_scores = {
        "freshness": freshness_score,
        "role_maturity": maturity_score,
        "role_stability": change_score,
        "distribution_sharpness": sharpness_score,
        "simulation_support": simulation_score,
        "expert_agreement": agreement_score,
        "variance_control": variance_score,
    }
    weights = {
        "freshness": 0.20,
        "role_maturity": 0.16,
        "role_stability": 0.16,
        "distribution_sharpness": 0.14,
        "simulation_support": 0.10,
        "expert_agreement": 0.12,
        "variance_control": 0.12,
    }
    score = 100.0 * sum(component_scores[key] * weights[key] for key in weights)

    flags: list[str] = []
    if freshness_hours is None:
        flags.append("MISSING_EVIDENCE_FRESHNESS")
    elif freshness_hours > float(max_evidence_age_hours):
        flags.append("STALE_EVIDENCE")
    if maturity_score < 0.40:
        flags.append("IMMATURE_ROLE_STATE")
    if float(snapshot.role.role_change_probability) > 0.55:
        flags.append("ROLE_CHANGE_RISK")
    if relative_width > 1.5:
        flags.append("WIDE_PREDICTIVE_INTERVAL")
    if simulation_rows < minimum_simulations:
        flags.append("LOW_MONTE_CARLO_SUPPORT")
    if disagreement > disagreement_scale * 0.60:
        flags.append("HIGH_EXPERT_DISAGREEMENT")

    hard_data_risk = "STALE_EVIDENCE" in flags or "LOW_MONTE_CARLO_SUPPORT" in flags
    if hard_data_risk or score < 45:
        grade = "D"
        policy = "VERIFY_DATA"
    elif score < 62:
        grade = "C"
        policy = "MONITOR"
    elif score < 78:
        grade = "B"
        policy = "LEAN"
    else:
        grade = "A"
        policy = "ACT"

    return ForecastTrustReport(
        score=float(np.clip(score, 0.0, 100.0)),
        grade=grade,
        action_policy=policy,
        flags=tuple(flags),
        evidence_age_hours=freshness_hours,
        relative_interval_width=float(relative_width),
        simulation_rows=simulation_rows,
        component_scores=component_scores,
    )
