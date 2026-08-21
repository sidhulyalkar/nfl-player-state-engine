from __future__ import annotations

from player_state_engine.player_state import EvidenceTier, ExperimentEvidence, PairedEffectEstimate


def test_downstream_evidence_tier_requires_downstream_decision_evidence() -> None:
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
    missing_downstream = ExperimentEvidence(
        experiment_id="downstream-tier-without-downstream-evidence",
        evidence_tier=EvidenceTier.MULTI_SEASON_DOWNSTREAM,
        primary_metric="pinball",
        effect=effect,
        season_consistency=1.0,
        position_consistency=1.0,
        coverage=1.0,
        source_availability=1.0,
        negative_control_passed=True,
        downstream_decision_passed=None,
        preregistered=True,
        minimum_useful_effect=0.05,
    )
    assert not missing_downstream.promotion_eligible

    validated = ExperimentEvidence(
        experiment_id="downstream-tier-with-downstream-evidence",
        evidence_tier=EvidenceTier.MULTI_SEASON_DOWNSTREAM,
        primary_metric="pinball",
        effect=effect,
        season_consistency=1.0,
        position_consistency=1.0,
        coverage=1.0,
        source_availability=1.0,
        negative_control_passed=True,
        downstream_decision_passed=True,
        preregistered=True,
        minimum_useful_effect=0.05,
    )
    assert validated.promotion_eligible
