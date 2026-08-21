from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.player_state import (
    DynamicRoleFilter,
    EvidenceTier,
    ExecutionState,
    ExperimentEvidence,
    HierarchicalForecastFusion,
    PairedEffectEstimate,
    PlayerStateGraph,
    PlayerStateSnapshot,
    RecencyWeightedConditionalConformal,
    ShareObservation,
    TeamVolumeState,
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


def test_qb_total_carries_respect_team_carry_share_without_double_counting_scrambles() -> None:
    cutoff = datetime(2025, 9, 10, 16, tzinfo=UTC)
    role_filter = DynamicRoleFilter("qb-carry", "QB", prior_strength=10.0, maturity_rows=40.0)
    role_filter.fit(
        [
            ShareObservation(
                observed_at=datetime(2025, 9, 8, 16, tzinfo=UTC),
                available_for_prediction_at=datetime(2025, 9, 9, 16, tzinfo=UTC),
                shares={"snap_share": 0.99, "carry_share": 0.28},
                opportunities={"snap_share": 65, "carry_share": 28},
            )
        ],
        prediction_cutoff=cutoff,
    )
    snapshot = PlayerStateSnapshot(
        player_id="qb-carry",
        position="QB",
        role=role_filter.posterior(as_of=cutoff),
        team_volume=TeamVolumeState(42.0, 5.0, 22.0, 3.0),
        execution=ExecutionState(scramble_rate=0.18),
        p_active=1.0,
    )
    draws = PlayerStateGraph(LeagueConfig()).simulate(snapshot, simulations=1000, seed=91)
    assert (draws["carries"] <= draws["team_rushes"] + 1e-12).all()
    assert (draws["passing_completions"] <= draws["passing_attempts"] + 1e-12).all()
