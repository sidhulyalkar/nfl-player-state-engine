from __future__ import annotations

from pathlib import Path

import pandas as pd

from player_state_engine.product.schemas import (
    FantasyManager,
    FantasyRoster,
    LeagueIdentity,
    LeagueSettings,
    LeagueSnapshot,
    RosterEntry,
)


def import_csv_league(
    *,
    league_id: str,
    league_name: str,
    season: int,
    rosters_path: str | Path,
    free_agents_path: str | Path | None = None,
    teams: int | None = None,
) -> LeagueSnapshot:
    """Import a platform-neutral roster CSV.

    Required columns: roster_id, team_name, platform_player_id.
    Optional columns: manager_id, manager_name, player_name, position, nfl_team,
    is_starter, is_injured_reserve, wins, losses, ties, points_for, points_against.
    """
    frame = pd.read_csv(rosters_path)
    required = {"roster_id", "team_name", "platform_player_id"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"Roster CSV missing columns: {sorted(missing)}")

    managers: dict[str, FantasyManager] = {}
    rosters: list[FantasyRoster] = []
    for roster_id, group in frame.groupby("roster_id", sort=False):
        row = group.iloc[0]
        manager_id = str(row.get("manager_id", roster_id))
        managers[manager_id] = FantasyManager(
            manager_id=manager_id,
            display_name=str(row.get("manager_name", row["team_name"])),
            team_name=str(row["team_name"]),
        )
        entries = [
            RosterEntry(
                platform_player_id=str(player["platform_player_id"]),
                canonical_player_id=str(player["canonical_player_id"])
                if pd.notna(player.get("canonical_player_id"))
                else None,
                player_name=str(player["player_name"])
                if pd.notna(player.get("player_name"))
                else None,
                position=str(player["position"]) if pd.notna(player.get("position")) else None,
                nfl_team=str(player["nfl_team"]) if pd.notna(player.get("nfl_team")) else None,
                roster_slot=str(player["roster_slot"])
                if pd.notna(player.get("roster_slot"))
                else None,
                is_starter=bool(player.get("is_starter", False)),
                is_injured_reserve=bool(player.get("is_injured_reserve", False)),
            )
            for _, player in group.iterrows()
        ]
        rosters.append(
            FantasyRoster(
                roster_id=str(roster_id),
                manager_id=manager_id,
                team_name=str(row["team_name"]),
                players=entries,
                wins=int(row.get("wins", 0) or 0),
                losses=int(row.get("losses", 0) or 0),
                ties=int(row.get("ties", 0) or 0),
                points_for=float(row.get("points_for", 0) or 0),
                points_against=float(row.get("points_against", 0) or 0),
            )
        )

    free_agents: list[RosterEntry] = []
    if free_agents_path:
        free = pd.read_csv(free_agents_path)
        for _, player in free.iterrows():
            free_agents.append(
                RosterEntry(
                    platform_player_id=str(player["platform_player_id"]),
                    canonical_player_id=str(player["canonical_player_id"])
                    if pd.notna(player.get("canonical_player_id"))
                    else None,
                    player_name=str(player["player_name"])
                    if pd.notna(player.get("player_name"))
                    else None,
                    position=str(player["position"]) if pd.notna(player.get("position")) else None,
                    nfl_team=str(player["nfl_team"]) if pd.notna(player.get("nfl_team")) else None,
                )
            )

    return LeagueSnapshot(
        identity=LeagueIdentity(
            league_id=league_id,
            platform="csv",
            name=league_name,
            season=season,
        ),
        settings=LeagueSettings(teams=teams or len(rosters), season=season),
        managers=list(managers.values()),
        rosters=rosters,
        free_agents=free_agents,
    )
