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

    def _get(self, path: str) -> Any:
        return self.client.get_json(f"{self.base_url}/{path.lstrip('/')}")

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
        state = self._get("state/nfl")
        player_map = self._get("players/nfl") if include_free_agents else {}

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
                entries.append(
                    RosterEntry(
                        platform_player_id=player_id,
                        canonical_player_id=player.get("gsis_id") or player.get("sportradar_id"),
                        player_name=player.get("full_name") or player.get("first_name"),
                        position=player.get("fantasy_positions", [player.get("position")])[0]
                        if player.get("fantasy_positions")
                        else player.get("position"),
                        nfl_team=player.get("team"),
                        is_starter=player_id in starters,
                        is_injured_reserve=player_id in reserve,
                    )
                )
            settings = roster.get("settings") or {}
            total_fpts = (
                float(settings.get("fpts", 0)) + float(settings.get("fpts_decimal", 0)) / 100.0
            )
            total_against = (
                float(settings.get("fpts_against", 0))
                + float(settings.get("fpts_against_decimal", 0)) / 100.0
            )
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
                position = player.get("fantasy_positions", [player.get("position")])[0]
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
                original_roster_id=str(pick.get("roster_id"))
                if pick.get("roster_id") is not None
                else None,
                current_roster_id=str(pick.get("owner_id"))
                if pick.get("owner_id") is not None
                else None,
            )
            for pick in traded_picks
        ]
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
                current_week=int(state.get("week")) if state.get("week") is not None else None,
                scoring=scoring,
                roster_positions=roster_positions,
                playoff_week_start=settings_payload.get("playoff_week_start"),
                waiver_type=str(settings_payload.get("waiver_type"))
                if settings_payload.get("waiver_type") is not None
                else None,
                faab_budget=float(settings_payload.get("waiver_budget", 0) or 0),
                dynasty=bool(settings_payload.get("type") == 2 or league.get("previous_league_id")),
                superflex="SUPER_FLEX" in roster_positions,
            ),
            managers=managers,
            rosters=normalized_rosters,
            free_agents=free_agents,
            draft_picks=picks,
            metadata={"nfl_state": state, "raw_status": league.get("status")},
        )
