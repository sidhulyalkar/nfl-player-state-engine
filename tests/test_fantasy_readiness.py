from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import assess_league_readiness


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"player_id": "QB1", "position": "QB", "season_points_q10": 200, "season_points_q50": 250, "season_points_q90": 300, "market_adp": 20},
            {"player_id": "RB1", "position": "RB", "season_points_q10": 150, "season_points_q50": 210, "season_points_q90": 270, "market_adp": 10},
            {"player_id": "WR1", "position": "WR", "season_points_q10": 140, "season_points_q50": 205, "season_points_q90": 275, "market_adp": 11},
            {"player_id": "TE1", "position": "TE", "season_points_q10": 100, "season_points_q50": 160, "season_points_q90": 220, "market_adp": 40},
        ]
    )


def test_readiness_fails_loudly_when_required_defense_and_kicker_are_absent() -> None:
    config = LeagueConfig(
        teams=8,
        roster_slots={"QB": 2, "RB": 3, "WR": 3, "TE": 1, "FLEX": 3, "DEF": 1, "K": 1},
    )
    report = assess_league_readiness(_rows(), config)
    assert not report.ready
    assert {"DEF", "K"}.issubset(set(report.missing_positions))
    assert "MISSING_REQUIRED_POSITIONS" in report.flags


def test_readiness_allows_complete_core_pool_but_marks_generic_scoring_fallback() -> None:
    config = LeagueConfig(
        teams=12,
        scoring="half_ppr",
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1},
    )
    report = assess_league_readiness(_rows(), config)
    assert report.ready
    assert not report.missing_positions
    assert report.market_adp_coverage == 1.0
    assert report.valuation_coverage == 1.0
    assert "GENERIC_SCORING_FALLBACK" in report.flags


def test_duplicate_player_ids_are_a_hard_failure() -> None:
    frame = pd.concat([_rows(), _rows().iloc[[0]]], ignore_index=True)
    config = LeagueConfig(teams=12)
    report = assess_league_readiness(frame, config)
    assert not report.ready
    assert "DUPLICATE_PLAYER_IDS" in report.flags
