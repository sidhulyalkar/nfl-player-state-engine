from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.config import FeatureConfig
from player_state_engine.data.synthetic import generate_synthetic_dataset
from player_state_engine.features.weekly import (
    build_prediction_slate,
    build_weekly_features,
    calculate_fantasy_points_ppr,
    feature_columns,
    feature_columns_for_target,
)


def test_fantasy_scoring_formula() -> None:
    dataset = generate_synthetic_dataset(seasons=(2024,), weeks_per_season=4, seed=3)
    scored = calculate_fantasy_points_ppr(dataset.player_stats)
    assert np.isfinite(scored).all()
    assert (scored >= -10).all()


def test_current_outcome_does_not_leak_into_current_features() -> None:
    dataset = generate_synthetic_dataset(seasons=(2024,), weeks_per_season=6, seed=4)
    original = dataset.player_stats.copy()
    row_index = original.index[(original["position"] == "WR") & (original["week"] == 5)][0]
    altered = original.copy()
    altered.loc[row_index, "receiving_yards"] += 10_000
    altered.loc[row_index, "fantasy_points_ppr"] += 1_000

    left = build_weekly_features(original, dataset.schedules, FeatureConfig())
    right = build_weekly_features(altered, dataset.schedules, FeatureConfig())
    player_id = original.loc[row_index, "player_id"]
    selector = (left["player_id"] == player_id) & (left["week"] == 5)
    feature_names = [
        "receiving_yards_lag1",
        "receiving_yards_roll3_mean",
        "fantasy_points_ppr_ewm_h4",
        "position_receiving_yards_prior4",
        "team_receiving_yards_roll4",
    ]
    np.testing.assert_allclose(
        left.loc[selector, feature_names].to_numpy(dtype=float),
        right.loc[selector, feature_names].to_numpy(dtype=float),
        equal_nan=True,
    )


def test_prediction_slate_uses_only_prior_games() -> None:
    dataset = generate_synthetic_dataset(seasons=(2023, 2024), weeks_per_season=8, seed=5)
    extended = generate_synthetic_dataset(seasons=(2023, 2024), weeks_per_season=9, seed=5)
    slate = build_prediction_slate(
        dataset.player_stats,
        extended.schedules,
        season=2024,
        week=9,
        config=FeatureConfig(active_lookback_weeks=4),
    )
    assert not slate.empty
    assert slate["is_projection_row"].all()
    assert (slate["week"] == 9).all()
    assert slate["fantasy_points_ppr_lag1"].notna().any()


def test_feature_columns_reject_same_week_raw_outcomes() -> None:
    frame = pd.DataFrame(
        {
            "season": [2024],
            "week": [1],
            "position": ["WR"],
            "recent_team": ["SF"],
            "opponent_team": ["NYJ"],
            "receiving_yards": [80.0],
            "receiving_epa": [4.2],
            "receiving_first_downs": [5],
            "receiving_yards_lag1": [72.0],
            "receiving_yards_roll5_mean": [68.0],
            "persona_training_focus": [0.4],
        }
    )
    columns = feature_columns(frame, targets=("receiving_yards",))
    assert "receiving_epa" not in columns
    assert "receiving_first_downs" not in columns
    assert "receiving_yards" not in columns
    assert "receiving_yards_lag1" in columns
    assert "receiving_yards_roll5_mean" in columns
    assert "persona_training_focus" in columns


def test_target_feature_selector_is_compact() -> None:
    frame = pd.DataFrame(
        {
            "season": [2024],
            "week": [2],
            "position": ["WR"],
            "recent_team": ["SF"],
            "opponent_team": ["SEA"],
            "targets_lag1": [8.0],
            "passing_yards_lag1": [250.0],
            "receiving_yards_roll5_mean": [70.0],
            "team_targets_roll4": [30.0],
        }
    )
    columns = feature_columns_for_target(frame, "receiving_yards")
    assert "targets_lag1" in columns
    assert "receiving_yards_roll5_mean" in columns
    assert "passing_yards_lag1" not in columns
