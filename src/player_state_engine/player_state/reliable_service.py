from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.player_state.graph import PlayerStateSnapshot
from player_state_engine.player_state.service import (
    PlayerForecastBundle,
    PlayerStateForecastService,
)
from player_state_engine.player_state.trust import ForecastTrustReport, assess_forecast_trust


@dataclass(frozen=True, slots=True)
class ReliablePlayerForecastBundle:
    forecast: PlayerForecastBundle
    trust: ForecastTrustReport

    @property
    def action_policy(self) -> str:
        return self.trust.action_policy

    def as_dict(self) -> dict[str, object]:
        return {
            "summary": dict(self.forecast.summary),
            "intelligence_card": self.forecast.intelligence_card.as_dict(),
            "uncertainty": self.forecast.uncertainty.as_dict(),
            "trust": self.trust.as_dict(),
        }


class ReliablePlayerStateForecastService:
    """Decision-safe wrapper around the research Player State Graph service."""

    def __init__(self, league: LeagueConfig) -> None:
        self.base = PlayerStateForecastService(league)

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
        as_of: datetime | None = None,
        max_evidence_age_hours: float = 72.0,
        minimum_simulations: int = 500,
    ) -> ReliablePlayerForecastBundle:
        forecast = self.base.forecast(
            snapshot,
            simulations=simulations,
            uncertainty_simulations=uncertainty_simulations,
            seed=seed,
            replacement_threshold=replacement_threshold,
            consensus_median=consensus_median,
            evidence_freshness=evidence_freshness,
        )
        trust = assess_forecast_trust(
            snapshot,
            forecast.draws,
            forecast.uncertainty,
            forecast.intelligence_card,
            as_of=as_of,
            max_evidence_age_hours=max_evidence_age_hours,
            minimum_simulations=minimum_simulations,
        )
        return ReliablePlayerForecastBundle(forecast=forecast, trust=trust)
