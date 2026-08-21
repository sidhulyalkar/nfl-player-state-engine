from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.player_state import (
    EvidenceTier,
    ExperimentEvidence,
    HierarchicalForecastFusion,
    PairedEffectEstimate,
    RecencyWeightedConditionalConformal,
    paired_block_bootstrap,
)


def test_promotion_gate_requires_consistency_coverage_and_source_availability() -> None:
    effect = PairedEffectEstimate(
        effect=-0.20,
        ci_low=-0.30,
        ci_high=-0.10,
        probability_improves=0.99,
        blocks=30,
        rows=1000,
        metric="pinball",
        lower_is_better=True,
    )
    evidence = ExperimentEvidence(
        experiment_id="hardening-gate",
        evidence_tier=EvidenceTier.MULTI_SEASON_ISOLATED,
        primary_metric="pinball",
        effect=effect,
        season_consistency=0.40,
        position_consistency=1.0,
        coverage=1.0,
        source_availability=1.0,
        negative_control_passed=True,
        downstream_decision_passed=None,
        preregistered=True,
        minimum_useful_effect=0.05,
    )
    assert not evidence.promotion_eligible


def test_paired_block_bootstrap_preserves_row_weighted_effect_with_unequal_blocks() -> None:
    frame = pd.DataFrame(
        {
            "season": [2025] * 10,
            "week": [1] + [2] * 9,
            "candidate": [0.0] + [2.0] * 9,
            "reference": [1.0] * 10,
        }
    )
    estimate = paired_block_bootstrap(
        frame,
        candidate_column="candidate",
        reference_column="reference",
        metric="loss",
        samples=500,
        seed=7,
    )
    assert estimate.effect == 0.8
    assert estimate.blocks == 2
    assert estimate.rows == 10


def _crossed_fusion_history(rows: int = 220) -> pd.DataFrame:
    actual = np.linspace(5.0, 25.0, rows)
    history = pd.DataFrame(
        {
            "actual": actual,
            "position": ["WR"] * rows,
            "target": ["fantasy_points"] * rows,
            "forecast_horizon": ["weekly"] * rows,
            "regime_maturity_bucket": ["high"] * rows,
        }
    )
    history["direct_q10"] = actual + 2.0
    history["direct_q50"] = actual
    history["direct_q90"] = actual - 2.0
    for expert, offset in (("world", 4.0), ("consensus", -4.0)):
        history[f"{expert}_q10"] = actual + offset - 2.0
        history[f"{expert}_q50"] = actual + offset
        history[f"{expert}_q90"] = actual + offset + 2.0
    return history


def test_fusion_repairs_crossed_expert_quantiles_consistently() -> None:
    history = _crossed_fusion_history()
    fusion = HierarchicalForecastFusion(min_group_rows=20, shrinkage_rows=20.0).fit(history)
    output = fusion.transform(history.drop(columns=["actual"]))
    assert output["fusion_input_quantiles_reordered"].all()
    assert (output["direct_q10"] <= output["direct_q50"]).all()
    assert (output["direct_q50"] <= output["direct_q90"]).all()
    assert (output["q10"] <= output["q50"]).all()
    assert (output["q50"] <= output["q90"]).all()


def test_recency_calibrator_surfaces_crossed_input_repair() -> None:
    actual = np.linspace(0.0, 10.0, 200)
    history = pd.DataFrame(
        {
            "actual": actual,
            "q10": actual - 1.0,
            "q50": actual,
            "q90": actual + 1.0,
        }
    )
    calibrator = RecencyWeightedConditionalConformal(min_group_rows=20).fit(history)
    forecasts = pd.DataFrame(
        {
            "q10": [12.0],
            "q50": [10.0],
            "q90": [8.0],
        }
    )
    output = calibrator.transform(forecasts)
    assert bool(output.loc[0, "conformal_input_quantiles_reordered"])
    assert output.loc[0, "q10"] <= output.loc[0, "q50"] <= output.loc[0, "q90"]
