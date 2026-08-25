from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from player_state_engine.evaluation.intelligence_provenance import (
    IntelligenceEvidenceProvenance,
)
from player_state_engine.state_graph.experiments import EvidenceTier


def test_missing_provenance_fails_closed_to_synthetic_only() -> None:
    provenance = IntelligenceEvidenceProvenance.synthetic_default()

    assert provenance.tier == EvidenceTier.SYNTHETIC_ONLY
    assert provenance.frozen_sample_id is None
    assert provenance.point_in_time_verified is False
    assert provenance.source_coverage_point_in_time_verified is False
    assert provenance.authority == "research_evidence_only"


def test_tier_two_requires_frozen_point_in_time_provenance() -> None:
    with pytest.raises(ValidationError, match=r"Tier-2\+ intelligence evidence"):
        IntelligenceEvidenceProvenance(
            evidence_tier=int(EvidenceTier.MULTI_SEASON_ISOLATED),
            frozen_sample_id="",
            point_in_time_verified=False,
            source_coverage_point_in_time_verified=False,
        )


def test_valid_tier_two_provenance_round_trips_from_json(tmp_path) -> None:
    path = tmp_path / "evidence_provenance.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "authority": "research_evidence_only",
                "evidence_tier": int(EvidenceTier.MULTI_SEASON_ISOLATED),
                "frozen_sample_id": "official-availability-2021-2024-v1",
                "point_in_time_verified": True,
                "source_coverage_point_in_time_verified": True,
                "description": "Frozen historical official-availability replay sample.",
            }
        ),
        encoding="utf-8",
    )

    provenance = IntelligenceEvidenceProvenance.load(path)

    assert provenance.tier == EvidenceTier.MULTI_SEASON_ISOLATED
    assert provenance.frozen_sample_id == "official-availability-2021-2024-v1"
    assert provenance.point_in_time_verified is True
    assert provenance.source_coverage_point_in_time_verified is True


def test_tier_one_can_describe_unverified_single_slice_without_promotion_authority() -> None:
    provenance = IntelligenceEvidenceProvenance(
        evidence_tier=int(EvidenceTier.SINGLE_HISTORICAL_SLICE),
        frozen_sample_id="exploratory-single-slice",
    )

    assert provenance.tier == EvidenceTier.SINGLE_HISTORICAL_SLICE
    assert provenance.point_in_time_verified is False
