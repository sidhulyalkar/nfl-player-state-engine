from __future__ import annotations

from player_state_engine.config import FeatureConfig, ModelConfig
from player_state_engine.data.synthetic import generate_synthetic_dataset
from player_state_engine.features.weekly import build_weekly_features, feature_columns
from player_state_engine.models.quantile import QuantileModelBundle


def test_quantile_predictions_are_monotonic() -> None:
    dataset = generate_synthetic_dataset(seasons=(2023, 2024), weeks_per_season=8, seed=8)
    featured = build_weekly_features(dataset.player_stats, dataset.schedules, FeatureConfig())
    featured = featured.loc[featured["player_history_count"] >= 2]
    features = feature_columns(featured, targets=("fantasy_points_ppr",))
    config = ModelConfig(
        targets=("fantasy_points_ppr",),
        quantiles=(0.1, 0.5, 0.9),
        max_iter=10,
        min_samples_leaf=5,
        random_seed=8,
    )
    bundle = QuantileModelBundle(config).fit(featured, features, targets=("fantasy_points_ppr",))
    predicted = bundle.predict(featured.tail(30))
    assert (predicted["fantasy_points_ppr_q10"] <= predicted["fantasy_points_ppr_q50"]).all()
    assert (predicted["fantasy_points_ppr_q50"] <= predicted["fantasy_points_ppr_q90"]).all()
    assert (predicted["fantasy_points_ppr_q10"] >= 0).all()
