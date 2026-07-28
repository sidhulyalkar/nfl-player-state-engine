from __future__ import annotations

from player_state_engine.config import FeatureConfig, ModelConfig
from player_state_engine.data.synthetic import generate_synthetic_dataset
from player_state_engine.evaluation.benchmark import run_multiseason_benchmark
from player_state_engine.features.weekly import build_weekly_features, feature_columns


def test_multiseason_benchmark_compares_three_methods() -> None:
    dataset = generate_synthetic_dataset(seasons=(2022, 2023), weeks_per_season=10, seed=11)
    featured = build_weekly_features(dataset.player_stats, dataset.schedules, FeatureConfig())
    features = feature_columns(featured, targets=("fantasy_points_ppr",))
    config = ModelConfig(
        targets=("fantasy_points_ppr",),
        quantiles=(0.1, 0.5, 0.9),
        max_iter=5,
        min_samples_leaf=5,
        random_seed=11,
    )
    result = run_multiseason_benchmark(
        featured,
        features,
        target="fantasy_points_ppr",
        config=config,
        min_train_weeks=8,
        retrain_every_weeks=4,
        rolling_window=5,
    )
    assert set(result.summary_metrics["method"]) == {
        "quantile_engine",
        "rolling_5",
        "position_prior",
    }
    assert {"QB", "RB", "WR", "TE"}.issubset(set(result.position_metrics["position"]))
    assert not result.quantile_calibration.empty
    assert not result.interval_calibration.empty
    assert result.predictions["actual"].notna().all()
