from __future__ import annotations

import pandas as pd
import pytest

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.preseason_league_score import (
    build_preseason_league_scored_dataset,
)


def _base() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": 2025,
                "player_id": "p1",
                "player_name": "Player One",
                "position": "RB",
                "recent_team": "A",
            },
            {
                "season": 2025,
                "player_id": "p2",
                "player_name": "Player Two",
                "position": "WR",
                "recent_team": "B",
            },
            {
                "season": 2025,
                "player_id": "p3",
                "player_name": "Zero Player",
                "position": "TE",
                "recent_team": "C",
            },
        ]
    )


def _stats() -> pd.DataFrame:
    common = {
        "season": 2025,
        "week": 1,
        "season_type": "REG",
        "passing_yards": 0.0,
        "passing_tds": 0.0,
        "interceptions": 0.0,
        "rushing_yards": 0.0,
        "rushing_tds": 0.0,
        "receptions": 0.0,
        "receiving_yards": 0.0,
        "receiving_tds": 0.0,
        "special_teams_tds": 0.0,
        "sack_fumbles_lost": 0.0,
        "rushing_fumbles_lost": 0.0,
        "receiving_fumbles_lost": 0.0,
        "passing_2pt_conversions": 0.0,
        "rushing_2pt_conversions": 0.0,
        "receiving_2pt_conversions": 0.0,
    }
    p1 = {
        **common,
        "player_id": "p1",
        "player_name": "Player One",
        "team": "A",
        "position": "RB",
        # Deliberately include a trick-play pass. Direct scoring must not discard it because the
        # player's roster position is RB.
        "passing_yards": 25.0,
        "passing_tds": 1.0,
        "rushing_yards": 100.0,
        "rushing_tds": 1.0,
        "receptions": 2.0,
        "receiving_yards": 30.0,
        "rushing_fumbles_lost": 1.0,
        "rushing_2pt_conversions": 1.0,
        "fantasy_points_ppr": 26.0,
    }
    p2 = {
        **common,
        "player_id": "p2",
        "player_name": "Player Two",
        "team": "B",
        "position": "WR",
        "receptions": 4.0,
        "receiving_yards": 60.0,
        "receiving_tds": 1.0,
        "receiving_2pt_conversions": 1.0,
        # The default league target intentionally excludes individual return-TD scoring, while
        # nflverse's published reference includes it at six points. The source audit must still
        # reconcile exactly under the separate upstream reference formula.
        "special_teams_tds": 1.0,
        "fantasy_points_ppr": 24.0,
    }
    return pd.DataFrame([p1, p2])


def test_direct_ppr_target_scores_actual_outcomes_before_modeling() -> None:
    dataset, diagnostics = build_preseason_league_scored_dataset(
        _base(), _stats(), LeagueConfig(scoring="ppr")
    )
    values = dataset.set_index("player_id")["league_fantasy_points"]

    assert values["p1"] == 26.0
    assert values["p2"] == 18.0
    assert values["p3"] == 0.0
    assert diagnostics.zero_score_rows == 1
    assert diagnostics.ppr_reference_contract == (
        "nflverse_calculate_stats_ppr_including_special_teams_tds"
    )
    assert diagnostics.ppr_reference_rows == 2
    assert diagnostics.ppr_reference_mae == 0.0
    assert diagnostics.ppr_reference_max_abs_error == 0.0
    assert diagnostics.source_columns["fumbles_lost"] == (
        "sack_fumbles_lost",
        "rushing_fumbles_lost",
        "receiving_fumbles_lost",
    )


def test_league_can_explicitly_score_individual_special_teams_touchdowns() -> None:
    config = LeagueConfig(scoring="ppr", scoring_weights={"special_teams_tds": 6.0})
    dataset, diagnostics = build_preseason_league_scored_dataset(_base(), _stats(), config)
    values = dataset.set_index("player_id")["league_fantasy_points"]

    assert values["p1"] == 26.0
    assert values["p2"] == 24.0
    assert diagnostics.source_columns["special_teams_tds"] == ("special_teams_tds",)


def test_half_ppr_target_changes_only_the_league_scoring_contract() -> None:
    dataset, _ = build_preseason_league_scored_dataset(
        _base(), _stats(), LeagueConfig(scoring="half_ppr")
    )
    values = dataset.set_index("player_id")["league_fantasy_points"]
    assert values["p1"] == 25.0
    assert values["p2"] == 16.0
    assert values["p3"] == 0.0


def test_missing_nonzero_scoring_source_fails_closed() -> None:
    stats = _stats().drop(columns=["receiving_2pt_conversions"])
    with pytest.raises(ValueError, match="two_point_conversions"):
        build_preseason_league_scored_dataset(_base(), stats, LeagueConfig(scoring="ppr"))
