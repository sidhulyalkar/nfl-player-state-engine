from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.state_graph.experiments import (
    EvidenceTier,
    ExperimentRecord,
    PromotionPolicy,
    paired_block_bootstrap,
)


def test_cluster_bootstrap_preserves_row_weighted_effect_with_unequal_weeks() -> None:
    frame = pd.DataFrame(
        {
            "season": [2025] * 10,
            "week": [1] + [2] * 9,
            "champion": [1.0] * 10,
            "challenger": [0.0] + [2.0] * 9,
        }
    )
    estimate = paired_block_bootstrap(
        frame,
        champion_column="champion",
        challenger_column="challenger",
        bootstrap_samples=600,
        seed=7,
    )
    assert estimate.effect == -0.8


def _record(**overrides: object) -> ExperimentRecord:
    values: dict[str, object] = {
        "experiment_id": "hardening",
        "challenger": "graph",
        "champion": "direct",
        "primary_metric": "weighted_interval_score",
        "evidence_tier": EvidenceTier.MULTI_SEASON_DOWNSTREAM,
        "effect": 0.20,
        "ci_low": 0.10,
        "ci_high": 0.30,
        "season_consistency": 1.0,
        "position_consistency": 1.0,
        "week_consistency": 1.0,
        "coverage": 1.0,
        "data_availability": 1.0,
        "negative_control_passed": True,
        "downstream_decision_effect": 0.05,
    }
    values.update(overrides)
    return ExperimentRecord(**values)  # type: ignore[arg-type]


def test_downstream_evidence_tier_cannot_promote_without_downstream_value() -> None:
    missing = PromotionPolicy().evaluate(_record(downstream_decision_effect=None))
    assert not missing.promoted
    assert "downstream_decision_evidence_missing_or_nonpositive" in missing.blockers

    validated = PromotionPolicy().evaluate(_record())
    assert validated.promoted


def test_nonfinite_coverage_and_consistency_fail_closed() -> None:
    record = PromotionPolicy().evaluate(
        _record(coverage=float("nan"), position_consistency=float("nan"))
    )
    assert not record.promoted
    assert "insufficient_coverage" in record.blockers
    assert "missing_position_consistency" in record.blockers
    assert np.isnan(record.coverage)
