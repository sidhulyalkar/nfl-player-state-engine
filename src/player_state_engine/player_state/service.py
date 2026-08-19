from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Mapping

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.player_state.core import DynamicRoleFilter, RolePosterior, ShareObservation
from player_state_engine.player_state.graph import (
    PlayerStateGraph,
    PlayerStateSnapshot,
    UncertaintyBreakdown,
)
from player_state_engine.player_state.insights import (
    PlayerIntelligenceCard,
    build_player_intelligence_card,
    scenario_summary,
)


@dataclass(frozen=True, slots=True)
class PlayerForecastBundle:
    snapshot: PlayerStateSnapshot
    draws: pd.DataFrame
    summary: Mapping[str, float]
    uncertainty: UncertaintyBreakdown
    intelligence_card: PlayerIntelligenceCard


class PlayerStateForecastService:
    """Thin orchestration boundary for the research Player State Graph.

    Keeping orchestration here lets API/CLI/product layers consume the graph without moving
    model mathematics into UI code. The service is intentionally parallel to the production
    direct quantile engine until historical promotion gates are passed.
    """

    def __init__(self, league: LeagueConfig) -> None:
        self.league = league
        self.graph = PlayerStateGraph(league)

    @staticmethod
    def estimate_role(
        player_id: str,
        position: str,
        observations: list[ShareObservation],
        *,
        prediction_cutoff: datetime,
        prior_strength: float = 12.0,
        half_life_weeks: float = 4.0,
    ) -> RolePosterior:
        role_filter = DynamicRoleFilter(
            player_id,
            position,
            prior_strength=prior_strength,
            half_life_weeks=half_life_weeks,
        )
        role_filter.fit(observations, prediction_cutoff=prediction_cutoff)
        return role_filter.posterior(as_of=prediction_cutoff)

    def forecast(
        self,
        snapshot: PlayerStateSnapshot,
        *,
        simulations: int = 3000,
        uncertainty_simulations: int = 1500,
        seed: int = 42,
        replacement_threshold: float | None = None,
        consensus_median: float | None = None,
        evidence_freshness: datetime | None = None,
    ) -> PlayerForecastBundle:
        draws = self.graph.simulate(snapshot, simulations=simulations, seed=seed)
        uncertainty = self.graph.decompose_uncertainty(
            snapshot,
            simulations=uncertainty_simulations,
            seed=seed + 100_003,
        )
        card = build_player_intelligence_card(
            snapshot,
            draws,
            uncertainty,
            replacement_threshold=replacement_threshold,
            consensus_median=consensus_median,
            evidence_freshness=evidence_freshness,
        )
        return PlayerForecastBundle(
            snapshot=snapshot,
            draws=draws,
            summary=self.graph.summarize(draws),
            uncertainty=uncertainty,
            intelligence_card=card,
        )

    def scenario(
        self,
        snapshot: PlayerStateSnapshot,
        name: str,
        *,
        simulations: int = 2000,
        seed: int = 42,
        threshold: float | None = None,
        **snapshot_changes: object,
    ):
        scenario_snapshot = replace(snapshot, **snapshot_changes)
        draws = self.graph.simulate(scenario_snapshot, simulations=simulations, seed=seed)
        return scenario_summary(name, draws, threshold=threshold)
