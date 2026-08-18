from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from typing import Any

from player_state_engine.integrations.base import LeagueImporter
from player_state_engine.product.schemas import (
    FantasyManager,
    FantasyRoster,
    LeagueIdentity,
    LeagueSettings,
    LeagueSnapshot,
    RosterEntry,
)


def _get(obj: object, *names: str, default: Any = None) -> Any:
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _as_list(value: object | None) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _owner_id(team: object) -> str:
    owners = _as_list(_get(team, "owners", "owner", default=[]))
    if not owners:
        return str(_get(team, "team_id", "teamId", default="unknown"))
    owner = owners[0]
    if isinstance(owner, dict):
        return str(owner.get("id") or owner.get("displayName") or owner.get("firstName") or owner)
    return str(owner)


def _player_entry(player: object) -> RosterEntry:
    player_id = str(_get(player, "playerId", "player_id", default=_get(player, "name", default="unknown")))
    name = _get(player, "name", "playerName")
    position = _get(player, "position", "eligibleSlots")
    if isinstance(position, (list, tuple)):
        position = position[0] if position else None
    lineup_slot = _get(player, "lineupSlot", "lineup_slot")
    lineup_text = str(lineup_slot) if lineup_slot is not None else None
    is_starter = bool(lineup_text and lineup_text.upper() not in {"BE", "BENCH", "IR", "RES"})
    is_ir = bool(lineup_text and lineup_text.upper() in {"IR", "RES"})
    return RosterEntry(
        platform_player_id=player_id,
        canonical_player_id=str(_get(player, "proId", "pro_id")) if _get(player, "proId", "pro_id") else None,
        player_name=str(name) if name is not None else None,
        position=str(position).upper() if position is not None else None,
        nfl_team=str(_get(player, "proTeam", "pro_team")) if _get(player, "proTeam", "pro_team") else None,
        roster_slot=lineup_text,
        is_starter=is_starter,
        is_injured_reserve=is_ir,
    )


class ESPNImporter(LeagueImporter):
    """Normalize ESPN Fantasy Football into the project's canonical LeagueSnapshot."""

    platform = "espn"

    def __init__(self, league_factory: Callable[..., object] | None = None) -> None:
        self._league_factory = league_factory

    def _factory(self) -> Callable[..., object]:
        if self._league_factory is not None:
            return self._league_factory
        try:
            from espn_api.football import League
        except ImportError as exc:
            raise RuntimeError(
                'ESPN support requires the optional dependency: pip install -e ".[espn]"'
            ) from exc
        return League

    def import_league(
        self,
        league_id: str,
        *,
        season: int,
        espn_s2: str | None = None,
        swid: str | None = None,
        espn_s2_env: str = "PSE_ESPN_S2",
        swid_env: str = "PSE_ESPN_SWID",
        external_user_id: str | None = None,
        include_free_agents: bool = True,
        free_agent_limit: int = 300,
    ) -> LeagueSnapshot:
        s2 = espn_s2 or os.getenv(espn_s2_env)
        resolved_swid = swid or os.getenv(swid_env)
        kwargs: dict[str, Any] = {"league_id": int(league_id), "year": int(season)}
        if s2:
            kwargs["espn_s2"] = s2
        if resolved_swid:
            kwargs["swid"] = resolved_swid
        league = self._factory()(**kwargs)

        settings_obj = _get(league, "settings", default=None)
        league_name = _get(settings_obj, "name", default=None) or _get(league, "name", default=None)
        teams_raw = _as_list(_get(league, "teams", default=[]))

        managers: list[FantasyManager] = []
        rosters: list[FantasyRoster] = []
        owned_ids: set[str] = set()
        for team in teams_raw:
            team_id = str(_get(team, "team_id", "teamId", default=len(rosters) + 1))
            owner_id = _owner_id(team)
            team_name = str(_get(team, "team_name", "teamName", default=f"Team {team_id}"))
            managers.append(
                FantasyManager(manager_id=owner_id, display_name=owner_id, team_name=team_name)
            )
            entries = [_player_entry(player) for player in _as_list(_get(team, "roster", default=[]))]
            owned_ids.update(entry.platform_player_id for entry in entries)
            rosters.append(
                FantasyRoster(
                    roster_id=team_id,
                    manager_id=owner_id,
                    team_name=team_name,
                    players=entries,
                    wins=int(_get(team, "wins", default=0) or 0),
                    losses=int(_get(team, "losses", default=0) or 0),
                    ties=int(_get(team, "ties", default=0) or 0),
                    points_for=float(_get(team, "points_for", "pointsFor", default=0.0) or 0.0),
                    points_against=float(
                        _get(team, "points_against", "pointsAgainst", default=0.0) or 0.0
                    ),
                )
            )

        free_agents: list[RosterEntry] = []
        if include_free_agents and hasattr(league, "free_agents"):
            try:
                candidates: Iterable[object] = league.free_agents(size=int(free_agent_limit))
                for player in candidates:
                    entry = _player_entry(player)
                    if entry.platform_player_id not in owned_ids:
                        free_agents.append(entry)
            except Exception:
                free_agents = []

        roster_positions: list[str] = []
        roster_settings = _get(settings_obj, "roster_settings", "rosterSettings", default={}) or {}
        if isinstance(roster_settings, dict):
            for slot, count in roster_settings.items():
                try:
                    roster_positions.extend([str(slot).upper()] * int(count))
                except (TypeError, ValueError):
                    continue

        scoring: dict[str, float] = {}
        scoring_format = _get(settings_obj, "scoring_format", "scoringFormat", default={}) or {}
        if isinstance(scoring_format, dict):
            for key, value in scoring_format.items():
                try:
                    scoring[str(key)] = float(value)
                except (TypeError, ValueError):
                    continue

        draft_rows: list[dict[str, Any]] = []
        for pick in _as_list(_get(league, "draft", default=[])):
            draft_rows.append(
                {
                    "player_id": str(_get(pick, "playerId", "player_id", default="")),
                    "player_name": _get(pick, "playerName", "player_name"),
                    "round": _get(pick, "round_num", "roundNum"),
                    "round_pick": _get(pick, "round_pick", "roundPick"),
                    "overall_pick": _get(pick, "overall_pick", "overallPick"),
                    "team_id": str(_get(_get(pick, "team", default=None), "team_id", default="")),
                }
            )

        current_week = _get(league, "nfl_week", "current_week", default=None)
        team_count = int(_get(settings_obj, "team_count", "teamCount", default=len(rosters)) or len(rosters))
        superflex = any(slot in {"OP", "SUPER_FLEX", "SUPERFLEX", "SF"} for slot in roster_positions)

        return LeagueSnapshot(
            identity=LeagueIdentity(
                league_id=str(league_id),
                platform="espn",
                name=str(league_name or f"ESPN League {league_id}"),
                season=int(season),
                source_url=f"https://fantasy.espn.com/football/league?leagueId={league_id}",
                external_user_id=external_user_id,
            ),
            settings=LeagueSettings(
                teams=team_count,
                season=int(season),
                current_week=int(current_week) if current_week is not None else None,
                scoring=scoring,
                roster_positions=roster_positions,
                superflex=superflex,
                draft_type="snake",
            ),
            managers=managers,
            rosters=rosters,
            free_agents=free_agents,
            metadata={
                "live_draft_picks": draft_rows,
                "adapter": "espn-api",
                "credentials_present": bool(s2 and resolved_swid),
            },
        )
