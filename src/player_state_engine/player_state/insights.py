from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from player_state_engine.player_state.graph import PlayerStateSnapshot, UncertaintyBreakdown


@dataclass(frozen=True, slots=True)
class ProjectionChangeAttribution:
    before_median: float
    after_median: float
    total_change: float
    contributions: Mapping[str, float]
    method: str = "normalized_model_counterfactual_attribution"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScenarioSummary:
    name: str
    q10: float
    q50: float
    q90: float
    mean: float
    probability_above_threshold: float | None = None


@dataclass(frozen=True, slots=True)
class PlayerIntelligenceCard:
    player_id: str
    position: str
    median: float
    q10: float
    q90: float
    probability_top_12: float | None
    probability_top_24: float | None
    probability_below_replacement: float | None
    probability_active: float
    expected_routes: float
    expected_targets: float
    expected_carries: float
    expected_red_zone_opportunities: float
    role_state: str
    role_change_probability: float
    role_maturity: float
    projection_confidence: str
    main_upside_driver: str
    main_downside_driver: str
    consensus_disagreement: float | None
    evidence_freshness: datetime | None
    uncertainty: Mapping[str, float | str]
    source: str = "player_state_graph_research_challenger"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _points(draws: pd.DataFrame) -> np.ndarray:
    if "league_fantasy_points" not in draws:
        raise ValueError("draws must contain league_fantasy_points")
    values = pd.to_numeric(draws["league_fantasy_points"], errors="coerce").dropna().to_numpy(float)
    if not len(values):
        raise ValueError("draws contain no finite league_fantasy_points")
    return values


def _mean_column(draws: pd.DataFrame, column: str) -> float:
    if column not in draws:
        return 0.0
    return float(pd.to_numeric(draws[column], errors="coerce").fillna(0.0).mean())


def rank_probabilities(
    league_draws: pd.DataFrame,
    player_id: str,
    *,
    position_scope: bool = True,
) -> dict[str, float]:
    """Compute sample-wise top-12/top-24 probability without assuming independence."""

    required = {"simulation_id", "player_id", "position", "league_fantasy_points"}
    missing = required - set(league_draws.columns)
    if missing:
        raise ValueError(f"league draws missing columns: {sorted(missing)}")
    data = league_draws.copy()
    player_id = str(player_id)
    player_rows = data.loc[data["player_id"].astype(str).eq(player_id)]
    if player_rows.empty:
        raise ValueError(f"player_id {player_id!r} is absent from league draws")
    if position_scope:
        position = str(player_rows.iloc[0]["position"]).upper()
        data = data.loc[data["position"].astype(str).str.upper().eq(position)].copy()
    data["_rank"] = data.groupby("simulation_id")["league_fantasy_points"].rank(
        ascending=False, method="min"
    )
    ranks = data.loc[data["player_id"].astype(str).eq(player_id), "_rank"].to_numpy(float)
    return {
        "top_12": float(np.mean(ranks <= 12.0)),
        "top_24": float(np.mean(ranks <= 24.0)),
    }


def projection_change_attribution(
    before_median: float,
    after_median: float,
    raw_component_effects: Mapping[str, float],
) -> ProjectionChangeAttribution:
    """Normalize model counterfactual effects to the observed projection change.

    The output is explicitly model attribution, not a causal claim. The normalization keeps
    displayed components additive when the counterfactual total is identified. If component
    effects cancel exactly, the unexplained move is reported as a residual instead of assigning
    it arbitrarily to whichever component happened to appear first.
    """

    total = float(after_median) - float(before_median)
    raw = {str(key): float(value) for key, value in raw_component_effects.items()}
    raw_total = sum(raw.values())
    if abs(raw_total) <= 1e-12:
        contributions = dict(raw)
        residual = total - raw_total
        if abs(residual) > 1e-12 or not contributions:
            contributions["unattributed_residual"] = float(residual)
    else:
        scale = total / raw_total
        contributions = {key: float(value * scale) for key, value in raw.items()}
    return ProjectionChangeAttribution(
        before_median=float(before_median),
        after_median=float(after_median),
        total_change=total,
        contributions=contributions,
    )


def scenario_summary(
    name: str,
    draws: pd.DataFrame,
    *,
    threshold: float | None = None,
) -> ScenarioSummary:
    values = _points(draws)
    q10, q50, q90 = np.quantile(values, [0.10, 0.50, 0.90])
    return ScenarioSummary(
        name=str(name),
        q10=float(q10),
        q50=float(q50),
        q90=float(q90),
        mean=float(np.mean(values)),
        probability_above_threshold=(
            float(np.mean(values >= float(threshold))) if threshold is not None else None
        ),
    )


def upside_path(
    draws: pd.DataFrame,
    *,
    threshold: float,
    drivers: tuple[str, ...] = (
        "team_dropbacks",
        "team_rushes",
        "routes",
        "targets",
        "carries",
        "team_red_zone_plays",
    ),
) -> dict[str, float]:
    """Summarize the football states associated with the high-scoring tail."""

    if "league_fantasy_points" not in draws:
        raise ValueError("draws must contain league_fantasy_points")
    tail = draws.loc[pd.to_numeric(draws["league_fantasy_points"], errors="coerce") >= threshold]
    if tail.empty:
        return {"probability": 0.0}
    summary: dict[str, float] = {"probability": float(len(tail) / max(len(draws), 1))}
    for driver in drivers:
        if driver in tail:
            summary[driver] = float(pd.to_numeric(tail[driver], errors="coerce").mean())
    return summary


def _confidence_label(snapshot: PlayerStateSnapshot, uncertainty: UncertaintyBreakdown) -> str:
    maturity = float(snapshot.role.maturity)
    change = float(snapshot.role.role_change_probability)
    availability = float(snapshot.p_active)
    if availability < 0.75 or change > 0.70 or maturity < 0.25:
        return "low"
    if availability < 0.90 or change > 0.45 or maturity < 0.55:
        return "medium"
    if uncertainty.total_variance > 120.0:
        return "medium-high"
    return "high"


def _uncertainty_driver(uncertainty: UncertaintyBreakdown) -> str:
    pieces = {
        "availability": uncertainty.availability,
        "team volume": uncertainty.team_volume,
        "role/opportunity": uncertainty.role_opportunity,
        "execution": uncertainty.execution,
        "environment": uncertainty.environment,
        "residual model": uncertainty.residual_model,
    }
    return max(pieces, key=pieces.get)


def build_player_intelligence_card(
    snapshot: PlayerStateSnapshot,
    draws: pd.DataFrame,
    uncertainty: UncertaintyBreakdown,
    *,
    replacement_threshold: float | None = None,
    rank_probability: Mapping[str, float] | None = None,
    consensus_median: float | None = None,
    evidence_freshness: datetime | None = None,
    upside_driver: str | None = None,
    downside_driver: str | None = None,
) -> PlayerIntelligenceCard:
    values = _points(draws)
    q10, q50, q90 = np.quantile(values, [0.10, 0.50, 0.90])
    expected_routes = _mean_column(draws, "routes")
    expected_targets = _mean_column(draws, "targets")
    expected_carries = _mean_column(draws, "carries")
    expected_role_multiplier = 1.0 - float(snapshot.limited_probability) * (
        1.0 - float(snapshot.limited_role_multiplier)
    )
    expected_rz = (
        _mean_column(draws, "team_red_zone_plays")
        * snapshot.role.mean("red_zone_share", 0.0)
        * float(snapshot.p_active)
        * expected_role_multiplier
    )
    leading_uncertainty = _uncertainty_driver(uncertainty)
    if upside_driver is None:
        upside_driver = (
            "role expansion" if snapshot.role.role_change_probability >= 0.40 else "opportunity volume"
        )
    if downside_driver is None:
        downside_driver = leading_uncertainty
    return PlayerIntelligenceCard(
        player_id=str(snapshot.player_id),
        position=str(snapshot.position).upper(),
        median=float(q50),
        q10=float(q10),
        q90=float(q90),
        probability_top_12=(
            float(rank_probability["top_12"])
            if rank_probability and "top_12" in rank_probability
            else None
        ),
        probability_top_24=(
            float(rank_probability["top_24"])
            if rank_probability and "top_24" in rank_probability
            else None
        ),
        probability_below_replacement=(
            float(np.mean(values < replacement_threshold)) if replacement_threshold is not None else None
        ),
        probability_active=float(snapshot.p_active),
        expected_routes=expected_routes,
        expected_targets=expected_targets,
        expected_carries=expected_carries,
        expected_red_zone_opportunities=float(expected_rz),
        role_state=snapshot.role.role_label,
        role_change_probability=float(snapshot.role.role_change_probability),
        role_maturity=float(snapshot.role.maturity),
        projection_confidence=_confidence_label(snapshot, uncertainty),
        main_upside_driver=str(upside_driver),
        main_downside_driver=str(downside_driver),
        consensus_disagreement=(float(q50 - consensus_median) if consensus_median is not None else None),
        evidence_freshness=evidence_freshness,
        uncertainty=uncertainty.as_dict(),
    )
