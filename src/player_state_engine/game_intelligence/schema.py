from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum


class EvidenceAvailability(StrEnum):
    LIVE = "live"
    LIVE_FAIL_SOFT = "live_fail_soft"
    RETROSPECTIVE = "retrospective"
    MANUAL_LICENSED = "manual_or_licensed"


@dataclass(slots=True, frozen=True)
class MatchupSpec:
    season: int
    week: int
    home_team: str
    away_team: str
    home_spread: float = 0.0
    game_total: float = 44.0
    roof: str | None = None
    surface: str | None = None
    temperature: float | None = None
    wind: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class SimulationConfig:
    simulations: int = 1000
    max_plays: int = 190
    seed: int = 42
    minimum_seconds_per_play: int = 8
    maximum_seconds_per_play: int = 45
    fourth_down_aggression_scale: float = 1.0
    model_source: str = "play_by_play_simulator_v010_research"
    promoted: bool = False

    def __post_init__(self) -> None:
        if self.simulations < 1:
            raise ValueError("simulations must be positive")
        if self.max_plays < 20:
            raise ValueError("max_plays must be at least 20")


@dataclass(slots=True)
class SimulationPromotionDecision:
    promoted: bool
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    model_source: str = "game_simulation_promotion_gate_v010"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
