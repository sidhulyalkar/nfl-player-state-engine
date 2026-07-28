from __future__ import annotations

import pandas as pd

from player_state_engine.config import ContinualLearningConfig
from player_state_engine.learning.gates import evaluate_benchmark_gate
from player_state_engine.learning.registry import (
    ModelRecord,
    ModelRegistry,
    promote_model,
    register_model,
)


def _summary(engine: float, baseline: float, coverage: float = 0.8) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "method": "quantile_engine",
                "mean_pinball": engine,
                "mae": 2.0,
                "interval_coverage": coverage,
            },
            {"method": "rolling_5", "mean_pinball": baseline, "mae": 2.2, "interval_coverage": 0.8},
        ]
    )


def _positions(engine: float, baseline: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"position": "RB", "method": "quantile_engine", "mean_pinball": engine},
            {"position": "RB", "method": "rolling_5", "mean_pinball": baseline},
        ]
    )


def test_gate_approves_clean_improvement() -> None:
    decision = evaluate_benchmark_gate(
        _summary(0.9, 1.0),
        _positions(0.9, 1.0),
        ContinualLearningConfig(min_pinball_improvement_pct=2.0),
    )
    assert decision.approved
    assert decision.metrics["pinball_improvement_pct"] > 9.0


def test_gate_rejects_bad_calibration_and_subgroup_regression() -> None:
    decision = evaluate_benchmark_gate(
        _summary(0.95, 1.0, coverage=0.98),
        _positions(1.2, 1.0),
        ContinualLearningConfig(max_coverage_error=0.05, max_position_regression_pct=5.0),
    )
    assert not decision.approved
    assert len(decision.reasons) >= 2


def test_registry_promotes_one_champion_per_target() -> None:
    registry = ModelRegistry()
    first = ModelRecord(
        model_id="a",
        target="targets",
        training_end_fold_week=1,
        model_path="a.joblib",
        metrics_path="a.csv",
        status="approved",
    )
    second = ModelRecord(
        model_id="b",
        target="targets",
        training_end_fold_week=2,
        model_path="b.joblib",
        metrics_path="b.csv",
        status="approved",
    )
    register_model(registry, first)
    register_model(registry, second)
    promote_model(registry, "a")
    promote_model(registry, "b")
    assert registry.champions["targets"] == "b"
    assert registry.get("a").status == "approved"
    assert registry.get("b").status == "champion"
