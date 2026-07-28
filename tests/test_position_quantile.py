from __future__ import annotations

from player_state_engine.config import FeatureConfig, ModelConfig
from player_state_engine.data.synthetic import generate_synthetic_dataset
from player_state_engine.features.weekly import build_weekly_features, feature_columns_for_target
from player_state_engine.models.position_quantile import PositionSpecificQuantileBundle


def test_position_specific_bundle_predicts_all_trained_positions() -> None:
    dataset = generate_synthetic_dataset(seasons=(2023, 2024), weeks_per_season=8, seed=19)
    frame = build_weekly_features(dataset.player_stats, dataset.schedules, FeatureConfig())
    frame = frame[frame["player_history_count"] >= 1]
    features = feature_columns_for_target(frame, "carries")
    model = PositionSpecificQuantileBundle(
        ModelConfig(targets=("carries",), max_iter=5, min_samples_leaf=5)
    ).fit(frame, features, "carries", min_rows_per_position=20)
    predicted = model.predict(frame.tail(50))
    assert not predicted.empty
    assert "carries_q50" in predicted
