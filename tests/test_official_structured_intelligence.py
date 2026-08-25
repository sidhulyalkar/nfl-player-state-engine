from __future__ import annotations

from datetime import UTC, datetime

import pytest

from player_state_engine.intelligence.availability import OfficialAvailabilityEvidence
from player_state_engine.intelligence.official_claims import (
    canonicalize_official_availability,
    structured_claims_from_official_availability,
)
from player_state_engine.intelligence.structured import build_state_evidence_snapshots


def _evidence(event_type: str, **updates: object) -> OfficialAvailabilityEvidence:
    payload: dict[str, object] = {
        "evidence_id": f"official-{event_type}",
        "player_id": "p1",
        "observed_at_utc": datetime(2026, 9, 10, 18, 0, tzinfo=UTC),
        "source_url": "https://team.example.com/report",
        "event_type": event_type,
        "source_reliability": 0.98,
    }
    payload.update(updates)
    return OfficialAvailabilityEvidence.model_validate(payload)


def test_official_out_designation_is_strong_negative_availability_claim() -> None:
    claims = structured_claims_from_official_availability(
        _evidence("game_designation", game_status="out")
    )
    assert len(claims) == 1
    claim = claims[0]
    assert claim.domain == "availability"
    assert claim.latent_state == "availability"
    assert claim.direction == -1.0
    assert claim.magnitude == 1.0
    assert claim.provenance.evidence_class == "OFFICIAL"
    assert claim.provenance.available_at_utc == datetime(2026, 9, 10, 18, 0, tzinfo=UTC)
    assert claim.provenance.availability_basis == "collected"


def test_official_inactive_and_ir_are_hard_negative_evidence() -> None:
    inactive = structured_claims_from_official_availability(
        _evidence("inactive_list", is_inactive=True)
    )[0]
    reserve = structured_claims_from_official_availability(
        _evidence("injured_reserve", transaction_status="ir", game_status="ir")
    )[0]
    assert inactive.direction == -1.0
    assert reserve.direction == -1.0
    assert reserve.decay_half_life_days > inactive.decay_half_life_days


def test_depth_chart_maps_to_role_not_availability() -> None:
    claim = structured_claims_from_official_availability(
        _evidence("depth_chart", depth_role="backup", depth_rank=2)
    )[0]
    assert claim.domain == "role"
    assert claim.latent_state == "starter_security"
    assert claim.direction < 0
    assert claim.metadata["depth_rank"] == 2


def test_coach_workload_maps_fraction_onto_opportunity_state() -> None:
    high = structured_claims_from_official_availability(
        _evidence("coach_workload", expected_workload_fraction=0.8)
    )[0]
    low = structured_claims_from_official_availability(
        _evidence(
            "coach_workload",
            evidence_id="official-coach-low",
            expected_workload_fraction=0.2,
        )
    )[0]
    assert high.domain == "opportunity"
    assert high.latent_state == "snap_share"
    assert high.direction == pytest.approx(0.6)
    assert low.direction == pytest.approx(-0.6)


def test_unknown_coach_workload_does_not_invent_claim() -> None:
    assert structured_claims_from_official_availability(_evidence("coach_workload")) == []


def test_blank_official_evidence_id_fails_closed() -> None:
    with pytest.raises(ValueError, match="official evidence_id cannot be blank"):
        structured_claims_from_official_availability(
            _evidence("game_designation", evidence_id="   ", game_status="out")
        )


def test_official_claims_resolve_in_same_state_snapshot_as_news_contract() -> None:
    claims = canonicalize_official_availability(
        [
            _evidence("practice_participation", practice_status="limited"),
            _evidence(
                "game_designation",
                evidence_id="official-game-questionable",
                game_status="questionable",
            ),
        ]
    )
    frame = build_state_evidence_snapshots(
        claims,
        as_of_utc=datetime(2026, 9, 10, 18, 1, tzinfo=UTC),
    )
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["latent_state"] == "availability"
    assert row["high_authority_claim_count"] == 2
    assert row["source_count"] == 1
    assert row["consensus_signal"] < 0
    assert row["production_feature_enabled"] == False  # noqa: E712
