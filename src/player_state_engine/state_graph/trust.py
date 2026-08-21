from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from player_state_engine.state_graph.insights import PlayerIntelligenceCard
from player_state_engine.state_graph.types import PlayerLatentState, UncertaintyBreakdown


@dataclass(frozen=True, slots=True)
class ForecastTrustReport:
    """Decision-language guardrail for a research forecast, not a predictive probability."""

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


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


def assess_forecast_trust(
    state: PlayerLatentState,
    draws: pd.DataFrame,
    uncertainty: UncertaintyBreakdown,
    card: PlayerIntelligenceCard,
    *,
    as_of: datetime | None = None,
    max_evidence_age_hours: float = 72.0,
    minimum_simulations: int = 500,
) -> ForecastTrustReport:
    """Assess how strongly the product should communicate a graph forecast.

    A low score means the system should communicate cautiously. It does not mean the player is
    bad. Components intentionally focus on evidence freshness, role maturity/stability,
    distribution width, Monte Carlo support, expert agreement and residual model variance.
    """

    if "league_fantasy_points" not in draws:
        raise ValueError("draws must contain league_fantasy_points")
    values = pd.to_numeric(draws["league_fantasy_points"], errors="coerce").dropna().to_numpy(float)
    if not len(values):
        raise ValueError("draws contain no finite league_fantasy_points")

    now = _utc(as_of or datetime.now(UTC))
    evidence_time = _parse_timestamp(card.evidence_freshness or state.evidence_cutoff)
    if evidence_time is None:
        freshness_hours = None
        freshness_score = 0.35
    else:
        freshness_hours = max(0.0, (now - evidence_time).total_seconds() / 3600.0)
        freshness_score = float(
            np.exp(-freshness_hours / max(float(max_evidence_age_hours), 1.0))
        )

    maturity_score = {
        "LOW": 0.30,
        "MEDIUM": 0.65,
        "HIGH": 0.90,
    }.get(str(state.role.state_maturity).upper(), 0.45)
    change_score = _bounded(1.0 - float(state.role.aggregate_change_probability))

    q10, q50, q90 = np.quantile(values, [0.10, 0.50, 0.90])
    interval_width = float(max(q90 - q10, 0.0))
    relative_width = interval_width / max(abs(float(q50)), 5.0)
    sharpness_score = _bounded(1.0 - relative_width / 2.5)

    simulation_rows = int(len(values))
    simulation_score = _bounded(simulation_rows / max(float(minimum_simulations), 1.0))

    disagreement = abs(float(card.consensus_disagreement or 0.0))
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
    if float(state.role.aggregate_change_probability) > 0.55:
        flags.append("ROLE_CHANGE_RISK")
    if relative_width > 1.5:
        flags.append("WIDE_PREDICTIVE_INTERVAL")
    if simulation_rows < minimum_simulations:
        flags.append("LOW_MONTE_CARLO_SUPPORT")
    if disagreement > disagreement_scale * 0.60:
        flags.append("HIGH_EXPERT_DISAGREEMENT")

    hard_data_risk = "STALE_EVIDENCE" in flags or "LOW_MONTE_CARLO_SUPPORT" in flags
    if hard_data_risk or score < 45.0:
        grade = "D"
        action_policy = "VERIFY_DATA"
    elif score < 62.0:
        grade = "C"
        action_policy = "MONITOR"
    elif score < 78.0:
        grade = "B"
        action_policy = "LEAN"
    else:
        grade = "A"
        action_policy = "ACT"

    return ForecastTrustReport(
        score=float(np.clip(score, 0.0, 100.0)),
        grade=grade,
        action_policy=action_policy,
        flags=tuple(flags),
        evidence_age_hours=freshness_hours,
        relative_interval_width=float(relative_width),
        simulation_rows=simulation_rows,
        component_scores=component_scores,
    )
