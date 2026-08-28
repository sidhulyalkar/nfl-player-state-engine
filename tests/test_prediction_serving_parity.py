from __future__ import annotations

import pandas as pd
import pytest

from player_state_engine.features.serving import build_current_roster_prediction_slate


def _schedules() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"season": 2025, "week": 17, "game_type": "REG", "game_id": "2025_17_NYJ_NE", "away_team": "NYJ", "home_team": "NE"},
            {"season": 2025, "week": 17, "game_type": "REG", "game_id": "2025_17_BUF_MIA", "away_team": "BUF", "home_team": "MIA"},
            {"season": 2025, "week": 18, "game_type": "REG", "game_id": "2025_18_NE_NYJ", "away_team": "NE", "home_team": "NYJ"},
            {"season": 2025, "week": 18, "game_type": "REG", "game_id": "2025_18_MIA_BUF", "away_team": "MIA", "home_team": "BUF"},
            {"season": 2026, "week": 1, "game_type": "REG", "game_id": "2026_01_NYJ_NE", "away_team": "NYJ", "home_team": "NE"},
        ]
    )


def _history() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for week, game_id, team, player_id, position, attempts, targets, carries, points in [
        (17, "2025_17_NYJ_NE", "NE", "NE-QB", "QB", 32, 0, 3, 19.0),
        (17, "2025_17_NYJ_NE", "NE", "NE-WR", "WR", 0, 8, 0, 16.0),
        (17, "2025_17_NYJ_NE", "NYJ", "NYJ-QB", "QB", 29, 0, 2, 17.0),
        (17, "2025_17_NYJ_NE", "NYJ", "NYJ-WR", "WR", 0, 7, 0, 13.0),
        (17, "2025_17_BUF_MIA", "BUF", "TRADE-WR", "WR", 0, 9, 0, 15.0),
        (17, "2025_17_BUF_MIA", "BUF", "BUF-QB", "QB", 35, 0, 4, 24.0),
        (17, "2025_17_BUF_MIA", "MIA", "MIA-QB", "QB", 30, 0, 2, 18.0),
        (18, "2025_18_NE_NYJ", "NE", "NE-QB", "QB", 30, 0, 2, 18.0),
        (18, "2025_18_NE_NYJ", "NE", "NE-WR", "WR", 0, 10, 0, 18.0),
        (18, "2025_18_NE_NYJ", "NYJ", "NYJ-QB", "QB", 31, 0, 2, 20.0),
        (18, "2025_18_NE_NYJ", "NYJ", "NYJ-WR", "WR", 0, 8, 0, 14.0),
        (18, "2025_18_MIA_BUF", "BUF", "TRADE-WR", "WR", 0, 7, 0, 12.0),
        (18, "2025_18_MIA_BUF", "BUF", "BUF-QB", "QB", 33, 0, 3, 23.0),
        (18, "2025_18_MIA_BUF", "MIA", "MIA-QB", "QB", 28, 0, 3, 17.0),
    ]:
        rows.append(
            {
                "season": 2025,
                "week": week,
                "season_type": "REG",
                "game_id": game_id,
                "player_id": player_id,
                "player_name": player_id,
                "team": team,
                "position": position,
                "passing_attempts": attempts,
                "targets": targets,
                "carries": carries,
                "receptions": max(0, targets - 2),
                "passing_yards": attempts * 7,
                "receiving_yards": targets * 9,
                "rushing_yards": carries * 4,
                "fantasy_points_ppr": points,
            }
        )
    return pd.DataFrame(rows)


def _current_rosters() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"season": 2026, "team": "NE", "position": "WR", "status": "ACT", "full_name": "Trade Receiver", "gsis_id": "TRADE-WR"},
            {"season": 2026, "team": "NE", "position": "QB", "status": "ACT", "full_name": "NE Quarterback", "gsis_id": "NE-QB"},
            {"season": 2026, "team": "NE", "position": "RB", "status": "ACT", "full_name": "Rookie Runner", "gsis_id": "ROOKIE-RB"},
            {"season": 2026, "team": "NYJ", "position": "QB", "status": "ACT", "full_name": "Jets Quarterback", "gsis_id": "NYJ-QB"},
            {"season": 2026, "team": "NYJ", "position": "WR", "status": "ACT", "full_name": "Jets Receiver", "gsis_id": "NYJ-WR"},
            # Released rows are intentionally not candidates and must not be misreported as
            # unresolved active identities even if their GSIS ID is missing.
            {"season": 2026, "team": "NE", "position": "WR", "status": "UFA", "full_name": "Released Receiver", "gsis_id": None},
        ]
    )


def test_current_roster_slate_keeps_trades_and_rookies_without_name_matching() -> None:
    slate, diagnostics = build_current_roster_prediction_slate(
        _history(),
        _schedules(),
        _current_rosters(),
        season=2026,
        week=1,
    )

    assert set(slate["player_id"]) == {"TRADE-WR", "NE-QB", "ROOKIE-RB", "NYJ-QB", "NYJ-WR"}
    traded = slate.loc[slate["player_id"].eq("TRADE-WR")].iloc[0]
    rookie = slate.loc[slate["player_id"].eq("ROOKIE-RB")].iloc[0]

    assert traded["recent_team"] == "NE"
    assert int(traded["team_changed_prior"]) == 1
    assert int(rookie["player_history_count"]) == 0
    assert int(rookie["is_rookie_prior"]) == 1

    # These were missing in the old exact-week serving path even though training populated them.
    assert pd.notna(traded["position_fantasy_points_ppr_prior4"])
    assert pd.notna(traded["team_fantasy_points_ppr_roll4"])
    assert pd.notna(traded["opp_allowed_fantasy_points_ppr_roll4"])
    assert pd.notna(traded["previous_primary_qb"])

    assert diagnostics.excluded_roster_status_rows == 1
    assert diagnostics.unresolved_identity_rows == 0
    assert diagnostics.rookie_or_no_history_rows == 1
    assert diagnostics.team_change_rows >= 1
    assert diagnostics.projection_rows == 5


def test_contracted_row_without_gsis_id_fails_closed() -> None:
    rosters = _current_rosters()
    rosters.loc[len(rosters)] = {
        "season": 2026,
        "team": "NE",
        "position": "TE",
        "status": "ACT",
        "full_name": "Unknown Tight End",
        "gsis_id": None,
    }
    with pytest.raises(ValueError, match="without GSIS IDs"):
        build_current_roster_prediction_slate(
            _history(), _schedules(), rosters, season=2026, week=1
        )


def test_unknown_roster_status_requires_explicit_semantics() -> None:
    rosters = _current_rosters()
    rosters.loc[0, "status"] = "NEW_STATUS"
    with pytest.raises(ValueError, match="unknown roster statuses"):
        build_current_roster_prediction_slate(
            _history(), _schedules(), rosters, season=2026, week=1
        )


def test_cross_team_duplicate_without_timestamp_fails_closed() -> None:
    rosters = _current_rosters()
    rosters.loc[len(rosters)] = {
        "season": 2026,
        "team": "NYJ",
        "position": "WR",
        "status": "ACT",
        "full_name": "Trade Receiver",
        "gsis_id": "TRADE-WR",
    }
    with pytest.raises(ValueError, match="cross-team duplicate GSIS identities"):
        build_current_roster_prediction_slate(
            _history(), _schedules(), rosters, season=2026, week=1
        )
