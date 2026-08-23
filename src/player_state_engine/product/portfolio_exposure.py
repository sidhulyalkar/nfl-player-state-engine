from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

from player_state_engine.product.provenance import frame_records
from player_state_engine.product.schemas import FantasyRoster, LeagueSnapshot, RosterEntry
from player_state_engine.product.store import LeagueSnapshotStore


def _user_roster(snapshot: LeagueSnapshot) -> tuple[FantasyRoster | None, str | None]:
    """Resolve the imported user's roster without guessing.

    Imported platforms store the authenticated/external user id on LeagueIdentity and manager ids
    on each roster. If that relationship is unavailable, the portfolio layer reports the league as
    unresolved rather than arbitrarily selecting roster 1.
    """

    external_user_id = snapshot.identity.external_user_id
    if external_user_id:
        matches = [roster for roster in snapshot.rosters if roster.manager_id == external_user_id]
        if len(matches) == 1:
            return matches[0], "identity_external_user_id"
    metadata_roster_id = snapshot.metadata.get("user_roster_id") or snapshot.metadata.get(
        "selected_roster_id"
    )
    if metadata_roster_id is not None:
        matches = [roster for roster in snapshot.rosters if roster.roster_id == str(metadata_roster_id)]
        if len(matches) == 1:
            return matches[0], "snapshot_metadata"
    if len(snapshot.rosters) == 1:
        return snapshot.rosters[0], "single_roster_snapshot"
    return None, None


def _canonical_key(entry: RosterEntry, snapshot: LeagueSnapshot) -> tuple[str, str]:
    if entry.canonical_player_id:
        return str(entry.canonical_player_id), "canonical"
    # Platform ids can be compared within one platform, but are not claimed to be cross-platform IDs.
    return f"{snapshot.identity.platform}:{entry.platform_player_id}", "platform_scoped"


def build_portfolio_exposure(
    store: LeagueSnapshotStore,
    *,
    projections: pd.DataFrame | None = None,
) -> dict[str, object]:
    leagues: list[dict[str, object]] = []
    player_records: dict[str, dict[str, object]] = {}
    team_counts: Counter[str] = Counter()
    position_counts: Counter[str] = Counter()
    unresolved_leagues: list[dict[str, str]] = []
    id_quality: Counter[str] = Counter()
    league_ids = [str(row["league_id"]) for row in store.list()]

    for league_id in league_ids:
        try:
            snapshot = store.load(league_id)
        except (FileNotFoundError, ValueError):
            continue
        roster, resolution = _user_roster(snapshot)
        if roster is None:
            unresolved_leagues.append(
                {
                    "league_id": snapshot.identity.league_id,
                    "league_name": snapshot.identity.name,
                    "reason": "user_roster_not_resolved",
                }
            )
            continue
        leagues.append(
            {
                "league_id": snapshot.identity.league_id,
                "league_name": snapshot.identity.name,
                "platform": snapshot.identity.platform,
                "season": snapshot.identity.season,
                "roster_id": roster.roster_id,
                "team_name": roster.team_name,
                "resolution": resolution,
                "players": len(roster.players),
            }
        )
        for entry in roster.players:
            key, key_quality = _canonical_key(entry, snapshot)
            id_quality[key_quality] += 1
            record = player_records.setdefault(
                key,
                {
                    "player_key": key,
                    "canonical_player_id": entry.canonical_player_id,
                    "player_name": entry.player_name or key,
                    "position": entry.position,
                    "nfl_team": entry.nfl_team,
                    "leagues": [],
                    "starter_leagues": 0,
                    "identity_quality": key_quality,
                },
            )
            league_list = record["leagues"]
            if isinstance(league_list, list):
                league_list.append(
                    {
                        "league_id": snapshot.identity.league_id,
                        "league_name": snapshot.identity.name,
                        "team_name": roster.team_name,
                        "is_starter": entry.is_starter,
                        "roster_slot": entry.roster_slot,
                    }
                )
            if entry.is_starter:
                record["starter_leagues"] = int(record["starter_leagues"]) + 1
            if entry.nfl_team:
                team_counts[str(entry.nfl_team)] += 1
            if entry.position:
                position_counts[str(entry.position)] += 1

    resolved_league_count = len(leagues)
    projection_lookup = _projection_lookup(projections)
    output_players: list[dict[str, object]] = []
    for record in player_records.values():
        league_list = record.get("leagues")
        league_count = len(league_list) if isinstance(league_list, list) else 0
        record["league_count"] = league_count
        record["exposure_rate"] = league_count / resolved_league_count if resolved_league_count else None
        record["starter_exposure_rate"] = (
            int(record["starter_leagues"]) / resolved_league_count if resolved_league_count else None
        )
        canonical = record.get("canonical_player_id")
        projection = projection_lookup.get(str(canonical)) if canonical else None
        if projection is not None:
            record["projection"] = projection
        output_players.append(record)
    output_players.sort(
        key=lambda row: (
            -int(row.get("league_count") or 0),
            -int(row.get("starter_leagues") or 0),
            str(row.get("player_name") or ""),
        )
    )

    team_rows = _concentration_rows(team_counts, resolved_league_count, "nfl_team")
    position_rows = _concentration_rows(position_counts, resolved_league_count, "position")
    total_roster_slots = sum(team_counts.values())
    top_player_exposure = max(
        (float(row.get("exposure_rate") or 0.0) for row in output_players),
        default=0.0,
    )
    return {
        "data_mode": "PORTFOLIO",
        "authority": {
            "identity_aggregation": "canonical_when_available_platform_scoped_otherwise",
            "unresolved_leagues_are_excluded": True,
            "projection_values": "production_artifact_when_identity_matches",
            "note": (
                "Exposure describes roster concentration, not diversification utility. High exposure can "
                "be intentional; the surface exists to make correlated bets visible before another draft pick."
            ),
        },
        "summary": {
            "stored_leagues": len(league_ids),
            "resolved_user_rosters": resolved_league_count,
            "unresolved_user_rosters": len(unresolved_leagues),
            "unique_player_keys": len(output_players),
            "total_roster_slots": total_roster_slots,
            "maximum_single_player_exposure": top_player_exposure,
            "canonical_identity_rows": int(id_quality["canonical"]),
            "platform_scoped_identity_rows": int(id_quality["platform_scoped"]),
        },
        "leagues": leagues,
        "unresolved_leagues": unresolved_leagues,
        "players": output_players,
        "team_concentration": team_rows,
        "position_concentration": position_rows,
    }


def _projection_lookup(projections: pd.DataFrame | None) -> dict[str, dict[str, object]]:
    if projections is None or projections.empty or "player_id" not in projections:
        return {}
    frame = projections.copy()
    columns = [
        column
        for column in (
            "player_id",
            "fantasy_points_ppr_q10",
            "fantasy_points_ppr_q50",
            "fantasy_points_ppr_q90",
            "season_points_q10",
            "season_points_q50",
            "season_points_q90",
            "availability_probability",
            "opportunity_confidence",
            "model_version",
        )
        if column in frame
    ]
    frame = frame.loc[:, columns].drop_duplicates(subset=["player_id"], keep="last")
    records = frame_records(frame)
    return {str(row["player_id"]): row for row in records}


def _concentration_rows(
    counts: Counter[str],
    resolved_leagues: int,
    key_name: str,
) -> list[dict[str, object]]:
    denominator = max(resolved_leagues, 1)
    rows = [
        {
            key_name: key,
            "roster_slots": int(count),
            "slots_per_resolved_league": count / denominator,
        }
        for key, count in counts.items()
    ]
    rows.sort(key=lambda row: (-int(row["roster_slots"]), str(row[key_name])))
    return rows
