import pandas as pd

from player_state_engine.data.historical import canonicalize_injuries, resolve_snap_player_ids
from player_state_engine.evaluation.historical_sources import build_historical_source_features


def test_snap_crosswalk_and_prior_shift() -> None:
    panel = pd.DataFrame(
        {
            "season": [2021, 2021],
            "week": [1, 2],
            "game_id": ["g1", "g2"],
            "player_id": ["G1", "G1"],
            "player_name": ["Player One", "Player One"],
            "recent_team": ["AAA", "AAA"],
            "opponent_team": ["BBB", "CCC"],
            "position": ["RB", "RB"],
            "fantasy_points_ppr_q10": [2, 3],
            "fantasy_points_ppr_q50": [8, 9],
            "fantasy_points_ppr_q90": [18, 19],
            "actual_fantasy_points_ppr": [10, 12],
            "actual_carries": [10, 12],
            "actual_targets": [2, 3],
            "actual_receptions": [1, 2],
            "actual_receiving_yards": [5, 12],
            "actual_rushing_yards": [50, 65],
            "actual_passing_yards": [0, 0],
        }
    )
    snaps = pd.DataFrame(
        {
            "season": [2021, 2021],
            "week": [1, 2],
            "player": ["Player One", "Player One"],
            "pfr_player_id": ["P1", "P1"],
            "team": ["AAA", "AAA"],
            "position": ["RB", "RB"],
            "offense_snaps": [30, 45],
            "offense_pct": [50, 75],
        }
    )
    rosters = pd.DataFrame(
        {
            "season": [2021, 2021],
            "week": [1, 2],
            "gsis_id": ["G1", "G1"],
            "pfr_id": ["P1", "P1"],
            "full_name": ["Player One", "Player One"],
            "team": ["AAA", "AAA"],
            "position": ["RB", "RB"],
        }
    )
    resolved = resolve_snap_player_ids(snaps, rosters)
    assert set(resolved["player_id"]) == {"G1"}
    features, coverage = build_historical_source_features(
        panel, snap_counts=snaps, weekly_rosters=rosters
    )
    assert pd.isna(features.loc[features["week"].eq(1), "source_snap_share_lag1"]).all()
    assert features.loc[features["week"].eq(2), "source_snap_share_lag1"].iloc[0] == 0.5
    assert not coverage.empty


def test_injury_mapping_is_conservative() -> None:
    injuries = pd.DataFrame(
        {
            "season": [2024],
            "week": [3],
            "gsis_id": ["G1"],
            "full_name": ["Player"],
            "team": ["AAA"],
            "report_status": ["Questionable"],
            "practice_status": ["Limited Participation"],
            "date_modified": ["2024-09-20T18:00:00Z"],
        }
    )
    result = canonicalize_injuries(injuries)
    assert 0 < result["official_availability_prior"].iloc[0] < 1
