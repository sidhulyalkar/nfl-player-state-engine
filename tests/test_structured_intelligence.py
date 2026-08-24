from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from player_state_engine.intelligence.activation import (
    FeatureActivation,
    IntelligenceActivationRegistry,
    materialize_research_features,
)
from player_state_engine.intelligence.news import NewsClaim
from player_state_engine.intelligence.structured import (
    StructuredClaim,
    StructuredClaimLedger,
    build_state_evidence_snapshots,
    effective_claims_as_of,
    structured_claim_from_news,
)


def _news_claim(
    *,
    claim_id: str = "source:starter",
    player_id: str = "p1",
    direction: float = 1.0,
    published: datetime | None = None,
    collected: datetime | None = None,
    source_url: str = "https://example.com/a",
    evidence_class: str = "REPORTED",
) -> NewsClaim:
    authored = published or datetime(2026, 9, 9, 15, 0, tzinfo=UTC)
    collected_at = collected or authored + timedelta(hours=2)
    return NewsClaim(
        claim_id=claim_id,
        player_id=player_id,
        claim_type="starter_role",
        direction=direction,
        magnitude=1.0,
        source_url=source_url,
        published_at_utc=authored,
        collected_at_utc=collected_at,
        evidence_text="The team named the player the starter.",
        extractor_confidence=0.9,
        source_reliability=0.9,
        document_id=f"doc-{claim_id}",
        evidence_class=evidence_class,
        latent_state="starter_security",
        decay_half_life_days=14.0,
    )


def _clone_claim(claim: StructuredClaim, **updates: object) -> StructuredClaim:
    payload = claim.model_dump(mode="python", exclude={"content_sha256"})
    payload.update(updates)
    return StructuredClaim.model_validate(payload)


def test_collected_availability_basis_prevents_premature_use() -> None:
    published = datetime(2026, 9, 9, 15, 0, tzinfo=UTC)
    collected = datetime(2026, 9, 9, 17, 0, tzinfo=UTC)
    claim = structured_claim_from_news(
        _news_claim(published=published, collected=collected),
        availability_basis="collected",
    )
    assert claim.provenance.authored_at_utc == published
    assert claim.provenance.available_at_utc == collected

    early = build_state_evidence_snapshots(
        [claim], as_of_utc=datetime(2026, 9, 9, 16, 0, tzinfo=UTC)
    )
    assert early.empty

    late = build_state_evidence_snapshots(
        [claim], as_of_utc=datetime(2026, 9, 9, 18, 0, tzinfo=UTC)
    )
    assert len(late) == 1


def test_published_basis_is_explicit_and_auditable() -> None:
    published = datetime(2026, 9, 9, 15, 0, tzinfo=UTC)
    collected = datetime(2026, 9, 9, 17, 0, tzinfo=UTC)
    claim = structured_claim_from_news(
        _news_claim(published=published, collected=collected),
        availability_basis="published",
    )
    assert claim.provenance.available_at_utc == published
    assert claim.provenance.availability_basis == "published"


def test_contradictory_sources_remain_visible_as_disagreement() -> None:
    positive = structured_claim_from_news(
        _news_claim(
            claim_id="positive",
            direction=1.0,
            source_url="https://example.com/positive",
        )
    )
    negative = structured_claim_from_news(
        _news_claim(
            claim_id="negative",
            direction=-1.0,
            source_url="https://example.com/negative",
        )
    )
    cutoff = datetime(2026, 9, 9, 18, 0, tzinfo=UTC)
    frame = build_state_evidence_snapshots([positive, negative], as_of_utc=cutoff)
    row = frame.iloc[0]
    assert row["claim_count"] == 2
    assert row["source_count"] == 2
    assert row["conflict_score"] == pytest.approx(1.0)
    assert row["consensus_signal"] == pytest.approx(0.0)
    assert row["production_feature_enabled"] == False  # noqa: E712


def test_correction_changes_only_cutoffs_after_it_became_available() -> None:
    base = structured_claim_from_news(_news_claim(claim_id="original"))
    correction_time = base.available_at_utc + timedelta(hours=3)
    corrected_provenance = base.provenance.model_copy(
        update={
            "authored_at_utc": correction_time,
            "collected_at_utc": correction_time,
            "available_at_utc": correction_time,
            "supporting_evidence": "The earlier starter report was corrected.",
        }
    )
    retraction = StructuredClaim(
        claim_id="retraction-1",
        player_id=base.player_id,
        claim_type=base.claim_type,
        domain=base.domain,
        latent_state=base.latent_state,
        direction=0.0,
        magnitude=0.0,
        status="retracted",
        decay_half_life_days=base.decay_half_life_days,
        provenance=corrected_provenance,
        supersedes_claim_id=base.claim_id,
    )

    before = effective_claims_as_of(
        [base, retraction], as_of_utc=correction_time - timedelta(minutes=1)
    )
    after = effective_claims_as_of(
        [base, retraction], as_of_utc=correction_time + timedelta(minutes=1)
    )
    assert [claim.claim_id for claim in before] == [base.claim_id]
    assert after == []


def test_asserted_correction_can_replace_prior_claim() -> None:
    base = structured_claim_from_news(_news_claim(claim_id="original"))
    correction_time = base.available_at_utc + timedelta(hours=3)
    corrected_provenance = base.provenance.model_copy(
        update={
            "authored_at_utc": correction_time,
            "collected_at_utc": correction_time,
            "available_at_utc": correction_time,
            "supporting_evidence": "The player will instead serve as the backup.",
        }
    )
    replacement = StructuredClaim(
        claim_id="replacement-1",
        player_id=base.player_id,
        claim_type="backup_role",
        domain="role",
        latent_state="starter_security",
        direction=-0.65,
        magnitude=0.65,
        status="asserted",
        decay_half_life_days=14.0,
        provenance=corrected_provenance,
        supersedes_claim_id=base.claim_id,
    )
    effective = effective_claims_as_of(
        [base, replacement], as_of_utc=correction_time + timedelta(minutes=1)
    )
    assert [claim.claim_id for claim in effective] == [replacement.claim_id]


def test_ledger_is_idempotent_and_rejects_same_id_with_changed_content(tmp_path) -> None:
    ledger = StructuredClaimLedger(tmp_path)
    claim = structured_claim_from_news(_news_claim())
    assert ledger.save(claim) is True
    assert ledger.save(claim) is False

    changed = _clone_claim(claim, direction=-1.0)
    assert changed.claim_id == claim.claim_id
    assert changed.content_sha256 != claim.content_sha256
    with pytest.raises(ValueError, match="immutable structured claim conflict"):
        ledger.save(changed)


def test_ledger_detects_local_tampering(tmp_path) -> None:
    ledger = StructuredClaimLedger(tmp_path)
    claim = structured_claim_from_news(_news_claim())
    ledger.save(claim)
    path = ledger.claim_path(claim.claim_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["direction"] = -1.0
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="content_sha256"):
        ledger.load(claim.claim_id)


def test_ledger_as_of_query_excludes_future_claims(tmp_path) -> None:
    ledger = StructuredClaimLedger(tmp_path)
    claim = structured_claim_from_news(_news_claim())
    ledger.save(claim)
    assert ledger.claims(as_of_utc=claim.available_at_utc - timedelta(seconds=1)) == []
    assert [row.claim_id for row in ledger.claims(as_of_utc=claim.available_at_utc)] == [
        claim.claim_id
    ]


def test_activation_registry_defaults_fail_closed() -> None:
    registry = IntelligenceActivationRegistry()
    summary = registry.summary()
    assert summary["enabled"] == []
    assert "structured_news" in summary["disabled"]
    with pytest.raises(RuntimeError, match="frozen evidence"):
        materialize_research_features(
            pd.DataFrame({"player_id": ["p1"], "news_signal": [0.5]}),
            family="structured_news",
            registry=registry,
            feature_columns=["news_signal"],
        )


def test_enabled_family_requires_manual_evidence_metadata() -> None:
    with pytest.raises(ValueError, match="manual evidence metadata"):
        FeatureActivation(family="structured_news", status="enabled")

    enabled = FeatureActivation(
        family="structured_news",
        status="enabled",
        evidence_tier="tier_4_live_shadow",
        experiment_id="structured_news_ablation_2026",
        approved_by="human-review",
        approved_at_utc=datetime(2026, 10, 1, tzinfo=UTC),
    )
    registry = IntelligenceActivationRegistry([enabled])
    output = materialize_research_features(
        pd.DataFrame({"player_id": ["p1"], "news_signal": [0.5]}),
        family="structured_news",
        registry=registry,
        feature_columns=["news_signal"],
    )
    assert output.loc[0, "intelligence_feature_enabled"] == True  # noqa: E712
    assert output.loc[0, "intelligence_feature_family"] == "structured_news"


def test_automatic_intelligence_promotion_is_forbidden() -> None:
    with pytest.raises(ValueError, match="cannot be promoted automatically"):
        FeatureActivation(
            family="structured_news",
            status="shadow",
            automatic_promotion=True,
        )
