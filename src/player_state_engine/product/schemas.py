from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class LeagueSettings(BaseModel):
    teams: int = 12
    season: int
    current_week: int | None = None
    scoring: dict[str, float] = Field(default_factory=dict)
    roster_positions: list[str] = Field(default_factory=list)
    playoff_week_start: int | None = None
    waiver_type: str | None = None
    faab_budget: float | None = None
    dynasty: bool = False
    superflex: bool = False


class LeagueIdentity(BaseModel):
    league_id: str
    platform: Literal["sleeper", "yahoo", "fleaflicker", "csv", "manual", "demo"]
    name: str
    season: int
    imported_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_url: str | None = None
    external_user_id: str | None = None


class FantasyManager(BaseModel):
    manager_id: str
    display_name: str
    team_name: str | None = None
    avatar_url: str | None = None


class RosterEntry(BaseModel):
    platform_player_id: str
    canonical_player_id: str | None = None
    player_name: str | None = None
    position: str | None = None
    nfl_team: str | None = None
    roster_slot: str | None = None
    is_starter: bool = False
    is_injured_reserve: bool = False
    acquisition_type: str | None = None


class FantasyRoster(BaseModel):
    roster_id: str
    manager_id: str | None = None
    team_name: str
    players: list[RosterEntry] = Field(default_factory=list)
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    points_against: float = 0.0
    waiver_priority: int | None = None
    faab_remaining: float | None = None


class DraftPickAsset(BaseModel):
    season: int
    round: int
    original_roster_id: str | None = None
    current_roster_id: str | None = None


class LeagueSnapshot(BaseModel):
    identity: LeagueIdentity
    settings: LeagueSettings
    managers: list[FantasyManager] = Field(default_factory=list)
    rosters: list[FantasyRoster] = Field(default_factory=list)
    free_agents: list[RosterEntry] = Field(default_factory=list)
    draft_picks: list[DraftPickAsset] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def roster(self, roster_id: str) -> FantasyRoster:
        for roster in self.rosters:
            if roster.roster_id == str(roster_id):
                return roster
        raise KeyError(f"Unknown roster_id: {roster_id}")

    @property
    def owned_player_ids(self) -> set[str]:
        return {entry.platform_player_id for roster in self.rosters for entry in roster.players}


class PlayerProjectionCard(BaseModel):
    player_id: str
    player_name: str
    position: str
    nfl_team: str | None = None
    opponent: str | None = None
    week_q10: float | None = None
    week_q50: float | None = None
    week_q90: float | None = None
    season_q10: float | None = None
    season_q50: float | None = None
    season_q90: float | None = None
    availability_probability: float = 1.0
    opportunity_confidence: float = 0.5
    role_growth_score: float = 0.0
    scheme_fit_score: float = 0.0
    breakout_probability: float = 0.0
    trade_value: float | None = None
    decision_value: float | None = None
    owner_roster_id: str | None = None
    owner_team_name: str | None = None
    is_free_agent: bool = False
    reasons: list[str] = Field(default_factory=list)


class TradeAsset(BaseModel):
    player_id: str | None = None
    faab: float = 0.0
    draft_pick: DraftPickAsset | None = None

    @field_validator("faab")
    @classmethod
    def nonnegative_faab(cls, value: float) -> float:
        return max(0.0, float(value))


class TradeSide(BaseModel):
    roster_id: str
    assets: list[TradeAsset]


class TradeAnalysisRequest(BaseModel):
    league_id: str
    side_a: TradeSide
    side_b: TradeSide
    horizon: Literal["week", "rest_of_season", "dynasty"] = "rest_of_season"
    risk_preference: float = Field(default=0.5, ge=0.0, le=1.0)


class TeamTradeImpact(BaseModel):
    roster_id: str
    before_value: float
    after_value: float
    value_delta: float
    starter_delta: float
    floor_delta: float
    ceiling_delta: float
    depth_delta: float
    positional_need_delta: float
    probability_improves: float
    reasons: list[str]


class TradeAnalysis(BaseModel):
    league_id: str
    side_a: TeamTradeImpact
    side_b: TeamTradeImpact
    fairness_score: float
    mutual_benefit_score: float
    confidence: float
    verdict: Literal["strong_accept", "accept", "balanced", "decline", "strong_decline"]
    caveats: list[str] = Field(default_factory=list)


class TradeSuggestion(BaseModel):
    trade: TradeAnalysisRequest
    analysis: TradeAnalysis
    explanation: str


class NFLTeamState(BaseModel):
    team: str
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    point_differential: float
    win_percentage: float
    streak: str | None = None


class NFLStateSnapshot(BaseModel):
    season: int
    week: int | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    teams: list[NFLTeamState]
    metadata: dict[str, Any] = Field(default_factory=dict)
