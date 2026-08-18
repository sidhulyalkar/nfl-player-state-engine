from __future__ import annotations

from typing import Any

from player_state_engine.integrations.base import JsonClient, LeagueImporter
from player_state_engine.integrations.http import StandardLibraryJsonClient
from player_state_engine.product.schemas import (
    DraftPickAsset,
    FantasyManager,
    FantasyRoster,
    LeagueIdentity,
    LeagueSettings,
    LeagueSnapshot,
    RosterEntry,
)


class SleeperImporter(LeagueImporter):
    platform = "sleeper"
    base_url = "https://api.sleeper.app/v1"

    def __init__(self, client: JsonClient | None = None) -> None:
        self.client = client or StandardLibraryJsonClient()
        self._player_map_cache: dict[str, Any] | None = None
        self._state_cache: dict[str, Any] | None = None

    def _get(self, path: str) -> Any:
        return self.client.get_json(f"{self.base_url}/{path.lstrip('/')}")

    def _optional_get(self, path: str, default: Any) -> Any:
        try:
            return self._get(path)
        except (RuntimeError, AssertionError):
            return default

    def get_nfl_state(self, *, refresh: bool = False) -> dict[str, Any]:
        if self._state_cache is None or refresh:
            self._state_cache = dict(self._get("state/nfl") or {})
        return self._state_cache

    def get_player_map(self, *, refresh: bool = False) -> dict[str, Any]:
        if self._player_map_cache is None or refresh:
            payload = self._get("players/nfl") or {}
            self._player_map_cache = payload if isinstance(payload, dict) else {}
        return self._player_map_cache

    def get_user(self, username_or_user_id: str) -> dict[str, Any]:
        return dict(self._get(f"user/{username_or_user_id}") or {})

    def list_user_leagues(
        self, username_or_user_id: str, *, season: int | None = None
    ) -> list[dict[str, Any]]:
        user = self.get_user(username_or_user_id)
        user_id = str(user.get("user_id") or username_or_user_id)
        resolved_season = int(season or self.get_nfl_state().get("season"))
        payload = self._get(f"user/{user_id}/leagues/nfl/{resolved_season}") or []
        return [dict(item) for item in payload]

    def import_user_leagues(
        self,
        username_or_user_id: str,
        *,
        season: int | None = None,
        include_free_agents: bool = True,
        player_pool_limit: int | None = None,
    ) -> list[LeagueSnapshot]:
        user = self.get_user(username_or_user_id)
        user_id = str(user.get("user_id") or username_or_user_id)
        leagues = self.list_user_leagues(user_id, season=season)
        if include_free_agents:
            self.get_player_map()
        return [
            self.import_league(
                str(league["league_id"]),
                external_user_id=user_id,
                include_free_agents=include_free_agents,
                player_pool_limit=player_pool_limit,
            )
            for league in leagues
        ]

    def import_league(
        self,
        league_id: str,
        *,
        external_user_id: str | None = None,
        include_free_agents: bool = True,
        player_pool_limit: int | None = None,
    ) -> LeagueSnapshot:
        league = self._get(f"league/{league_id}")
        rosters = self._get(f"league/{league_id}/rosters")
        users = self._get(f"league/{league_id}/users")
        traded_picks = self._get(f"league/{league_id}/traded_picks")
        state = self.get_nfl_state()
        player_map = self.get_player_map() if include_free_agents else {}

        user_by_id = {str(user.get("user_id")): user for user in users}
        managers: list[FantasyManager] = []
        for user in users:
            metadata = user.get("metadata") or {}
            managers.append(
                FantasyManager(
                    manager_id=str(user.get("user_id")),
                    display_name=str(user.get("display_name") or user.get("username") or "Unknown"),
                    team_name=metadata.get("team_name"),
                    avatar_url=(
                        f"https://sleepercdn.com/avatars/{user['avatar']}"
                        if user.get("avatar")
                        else None
                    ),
                )
            )

        normalized_rosters: list[FantasyRoster] = []
        owned: set[str] = set()
        for roster in rosters:
            roster_id = str(roster.get("roster_id"))
            owner_id = str(roster.get("owner_id")) if roster.get("owner_id") is not None else None
            user = user_by_id.get(owner_id or "", {})
            metadata = user.get("metadata") or {}
            starters = {str(player_id) for player_id in (roster.get("starters") or [])}
            reserve = {str(player_id) for player_id in (roster.get("reserve") or [])}
            entries: list[RosterEntry] = []
            for player_id in roster.get("players") or []:
                player_id = str(player_id)
                owned.add(player_id)
                player = player_map.get(player_id, {}) if isinstance(player_map, dict) else {}
                fantasy_positions = player.get("fantasy_positions") or []
                entries.append(
                    RosterEntry(
                        platform_player_id=player_id,
                        canonical_player_id=player.get("gsis_id") or player.get("sportradar_id"),
                        player_name=player.get("full_name") or player.get("first_name"),
                        position=(fantasy_positions[0] if fantasy_positions else player.get("position")),
                        nfl_team=player.get("team"),
                        is_starter=player_id in starters,
                        is_injured_reserve=player_id in reserve,
                    )
                )
            settings = roster.get("settings") or {}
            total_fpts = float(settings.get("fpts", 0) or 0) + float(
                settings.get("fpts_decimal", 0) or 0
            ) / 100.0
            total_against = float(settings.get("fpts_against", 0) or 0) + float(
                settings.get("fpts_against_decimal", 0) or 0
            ) / 100.0
            budget_total = float(league.get("settings", {}).get("waiver_budget", 100) or 100)
            budget_used = float(settings.get("waiver_budget_used", 0) or 0)
            normalized_rosters.append(
                FantasyRoster(
                    roster_id=roster_id,
                    manager_id=owner_id,
                    team_name=str(
                        metadata.get("team_name")
                        or user.get("display_name")
                        or f"Roster {roster_id}"
                    ),
                    players=entries,
                    wins=int(settings.get("wins", 0) or 0),
                    losses=int(settings.get("losses", 0) or 0),
                    ties=int(settings.get("ties", 0) or 0),
                    points_for=total_fpts,
                    points_against=total_against,
                    waiver_priority=settings.get("waiver_position"),
                    faab_remaining=max(0.0, budget_total - budget_used),
                )
            )

        free_agents: list[RosterEntry] = []
        if include_free_agents and isinstance(player_map, dict):
            for player_id, player in player_map.items():
                if str(player_id) in owned or not player.get("active"):
                    continue
                fantasy_positions = player.get("fantasy_positions") or []
                position = fantasy_positions[0] if fantasy_positions else player.get("position")
                if position not in {"QB", "RB", "WR", "TE", "K", "DEF"}:
                    continue
                free_agents.append(
                    RosterEntry(
                        platform_player_id=str(player_id),
                        canonical_player_id=player.get("gsis_id") or player.get("sportradar_id"),
                        player_name=player.get("full_name") or player.get("first_name"),
                        position=position,
                        nfl_team=player.get("team"),
                    )
                )
                if player_pool_limit and len(free_agents) >= player_pool_limit:
                    break

        roster_positions = [str(slot) for slot in league.get("roster_positions", [])]
        settings_payload = league.get("settings") or {}
        scoring = {
            str(key): float(value) for key, value in (league.get("scoring_settings") or {}).items()
        }
        picks = [
            DraftPickAsset(
                season=int(pick["season"]),
                round=int(pick["round"]),
                original_roster_id=(
                    str(pick.get("roster_id")) if pick.get("roster_id") is not None else None
                ),
                current_roster_id=(
                    str(pick.get("owner_id")) if pick.get("owner_id") is not None else None
                ),
            )
            for pick in traded_picks
        ]

        current_week = int(state.get("week")) if state.get("week") is not None else None
        matchups = (
            self._optional_get(f"league/{league_id}/matchups/{current_week}", [])
            if current_week
            else []
        )
        drafts = self._optional_get(f"league/{league_id}/drafts", []) or []
        active_draft = next(
            (draft for draft in drafts if draft.get("status") in {"pre_draft", "drafting"}),
            drafts[0] if drafts else None,
        )
        draft_picks_live: list[dict[str, Any]] = []
        if active_draft and active_draft.get("draft_id"):
            draft_picks_live = (
                self._optional_get(f"draft/{active_draft['draft_id']}/picks", []) or []
            )

        external_roster_id = None
        if external_user_id:
            external_roster_id = next(
                (
                    str(roster.get("roster_id"))
                    for roster in rosters
                    if str(roster.get("owner_id")) == str(external_user_id)
                ),
                None,
            )

        median_scoring = bool(
            settings_payload.get("league_average_match")
            or settings_payload.get("median_matchup")
            or settings_payload.get("median_scoring")
        )
        return LeagueSnapshot(
            identity=LeagueIdentity(
                league_id=str(league_id),
                platform="sleeper",
                name=str(league.get("name") or f"Sleeper League {league_id}"),
                season=int(league.get("season") or state.get("season")),
                source_url=f"https://sleeper.com/leagues/{league_id}",
                external_user_id=external_user_id,
            ),
            settings=LeagueSettings(
                teams=int(league.get("total_rosters") or len(normalized_rosters)),
                season=int(league.get("season") or state.get("season")),
                current_week=current_week,
                scoring=scoring,
                roster_positions=roster_positions,
                playoff_week_start=settings_payload.get("playoff_week_start"),
                waiver_type=(
                    str(settings_payload.get("waiver_type"))
                    if settings_payload.get("waiver_type") is not None
                    else None
                ),
                faab_budget=float(settings_payload.get("waiver_budget", 0) or 0),
                dynasty=bool(settings_payload.get("type") == 2 or league.get("previous_league_id")),
                superflex=any(
                    slot in {"SUPER_FLEX", "SUPERFLEX", "OP"} for slot in roster_positions
                ),
                median_scoring=median_scoring,
                draft_type=(str(active_draft.get("type")) if active_draft else None),
            ),
            managers=managers,
            rosters=normalized_rosters,
            free_agents=free_agents,
            draft_picks=picks,
            metadata={
                "nfl_state": state,
                "raw_status": league.get("status"),
                "matchups": matchups,
                "active_draft": active_draft,
                "live_draft_picks": draft_picks_live,
                "external_roster_id": external_roster_id,
            },
        )
