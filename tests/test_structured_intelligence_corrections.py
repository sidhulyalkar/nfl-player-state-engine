from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from player_state_engine.intelligence.news import NewsClaim
from player_state_engine.intelligence.structured import (
    StructuredClaim,
    StructuredClaimLedger,
    effective_claims_as_of,
    structured_claim_from_news,
)
from player_state_engine.product.structured_intelligence import StructuredIntelligenceArtifactStore


def _base_claim(*, player_id: str = "p1") -> StructuredClaim:
    published = datetime(2026, 9, 9, 15, 0, tzinfo=UTC)
    return structured_claim_from_news(
        NewsClaim(
            claim_id=f"base-{player_id}",
            player_id=player_id,
            claim_type="starter_role",
            direction=1.0,
            magnitude=1.0,
            source_url=f"https://example.com/{player_id}/base",
            published_at_utc=published,
            collected_at_utc=published + timedelta(hours=1),
            evidence_text="The player was reported as the starter.",
            extractor_confidence=0.9,
            source_reliability=0.9,
            document_id=f"doc-{player_id}-base",
            evidence_class="REPORTED",
            latent_state="starter_security",
            decay_half_life_days=14.0,
        )
    )


def _correction(
    base: StructuredClaim,
    *,
    claim_id: str = "correction-1",
    player_id: str | None = None,
    available_at=None,
    domain: str = "opportunity",
    latent_state: str = "snap_share",
) -> StructuredClaim:
    correction_time = available_at or base.available_at_utc + timedelta(hours=2)
    provenance = base.provenance.model_copy(
        update={
            "authored_at_utc": correction_time,
            "collected_at_utc": correction_time,
            "available_at_utc": correction_time,
            "supporting_evidence": "The earlier role report was corrected by later evidence.",
        }
    )
    return StructuredClaim(
        claim_id=claim_id,
        player_id=player_id or base.player_id,
        claim_type="corrected_opportunity_role",
        domain=domain,
        latent_state=latent_state,
        direction=-0.6,
        magnitude=0.6,
        status="asserted",
        decay_half_life_days=7.0,
        provenance=provenance,
        supersedes_claim_id=base.claim_id,
    )


def test_domain_filter_is_applied_after_cross_domain_correction_resolution(tmp_path) -> None:
    base = _base_claim()
    correction = _correction(base)
    ledger = StructuredClaimLedger(tmp_path)
    ledger.save(base)
    ledger.save(correction)
    assert ledger.health()["integrity_verified"] is True

    store = StructuredIntelligenceArtifactStore(
        tmp_path,
        activation_registry_path=tmp_path / "activation.json",
    )
    as_of = correction.available_at_utc + timedelta(minutes=1)
    role = store.snapshot(as_of_utc=as_of, player_id="p1", domain="role")
    assert role["claim_count"] == 1
    assert role["effective_claim_count"] == 0
    assert role["state_count"] == 0

    audit = store.claims_snapshot(as_of_utc=as_of, player_id="p1", domain="role")
    assert audit["total_matches"] == 1
    assert audit["claims"][0]["claim_id"] == base.claim_id
    assert audit["claims"][0]["effective_at_cutoff"] is False

    opportunity = store.snapshot(
        as_of_utc=as_of,
        player_id="p1",
        domain="opportunity",
    )
    assert opportunity["effective_claim_count"] == 1
    assert opportunity["state_count"] == 1


def test_orphan_correction_makes_complete_ledger_health_fail_closed(tmp_path) -> None:
    base = _base_claim()
    orphan = _correction(base, claim_id="orphan-1")
    payload = orphan.model_dump(mode="python", exclude={"content_sha256"})
    payload["supersedes_claim_id"] = "missing-claim"
    orphan = StructuredClaim.model_validate(payload)

    ledger = StructuredClaimLedger(tmp_path)
    ledger.save(orphan)
    health = ledger.health()
    assert health["integrity_verified"] is False
    assert any("orphan_correction:orphan-1->missing-claim" in item for item in health["integrity_failures"])


def test_cross_player_correction_is_rejected_by_resolution_and_health(tmp_path) -> None:
    base = _base_claim(player_id="p1")
    correction = _correction(base, player_id="p2", claim_id="cross-player")
    with pytest.raises(ValueError, match="different player"):
        effective_claims_as_of(
            [base, correction],
            as_of_utc=correction.available_at_utc + timedelta(minutes=1),
        )

    ledger = StructuredClaimLedger(tmp_path)
    ledger.save(base)
    ledger.save(correction)
    health = ledger.health()
    assert health["integrity_verified"] is False
    assert any("cross_player_correction" in item for item in health["integrity_failures"])


def test_correction_cannot_predate_the_claim_it_supersedes(tmp_path) -> None:
    base = _base_claim()
    correction = _correction(
        base,
        claim_id="time-travel",
        available_at=base.available_at_utc - timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="predates superseded claim"):
        effective_claims_as_of([base, correction], as_of_utc=base.available_at_utc)

    ledger = StructuredClaimLedger(tmp_path)
    ledger.save(base)
    ledger.save(correction)
    health = ledger.health()
    assert health["integrity_verified"] is False
    assert any("correction_predates_target" in item for item in health["integrity_failures"])


def test_structured_claim_cannot_supersede_itself() -> None:
    base = _base_claim()
    payload = base.model_dump(mode="python", exclude={"content_sha256"})
    payload["supersedes_claim_id"] = base.claim_id
    with pytest.raises(ValueError, match="cannot supersede itself"):
        StructuredClaim.model_validate(payload)
