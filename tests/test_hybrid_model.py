from __future__ import annotations

from player_state_engine.config import FeatureConfig, ModelConfig
from player_state_engine.data.synthetic import generate_synthetic_dataset
from player_state_engine.features.weekly import build_weekly_features, feature_columns
from player_state_engine.models.hybrid import HybridQuantileModelBundle
from player_state_engine.models.position_quantile import PositionSpecificQuantileBundle


def test_hybrid_routes_carries_and_preserves_rows(tmp_path) -> None:
    dataset = generate_synthetic_dataset(seasons=(2023, 2024), weeks_per_season=8, seed=27)
    frame = build_weekly_features(dataset.player_stats, dataset.schedules, FeatureConfig())
    frame = frame.loc[frame["player_history_count"] >= 1]
    features = feature_columns(frame, targets=("fantasy_points_ppr", "carries"))
    config = ModelConfig(
        targets=("fantasy_points_ppr", "carries"),
        max_iter=5,
        min_samples_leaf=5,
    )
    bundle = HybridQuantileModelBundle(config).fit(frame, features)
    assert isinstance(bundle.models["carries"], PositionSpecificQuantileBundle)
    sample = frame.tail(60)
    predicted = bundle.predict(sample)
    assert len(predicted) == len(sample)
    assert {"carries_q10", "carries_q50", "carries_q90"}.issubset(predicted.columns)

    path = bundle.save(tmp_path / "hybrid.joblib")
    restored = HybridQuantileModelBundle.load(path)
    assert len(restored.predict(sample)) == len(sample)
