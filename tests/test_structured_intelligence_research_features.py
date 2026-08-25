from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from player_state_engine.intelligence.research_features import (
    attach_canonical_structured_evidence,
)
from player_state_engine.intelligence.structured import ClaimProvenance, StructuredClaim


def _provenance(
    *,
    available_at: datetime,
    extractor_version: str,
    publisher_type: str,
    evidence_class: str = "REPORTED",
) -> ClaimProvenance:
    return ClaimProvenance(
        source_url=f"https://example.com/{available_at.timestamp()}",
        publisher_type=publisher_type,
        evidence_class=evidence_class,
        authored_at_utc=available_at,
        collected_at_utc=available_at,
        available_at_utc=available_at,
        availability_basis="collected",
        supporting_evidence="Timestamped test evidence.",
        extractor_version=extractor_version,
        extractor_confidence=1.0,
        source_reliability=1.0,
    )


def test_research_attachment_recomputes_retraction_at_each_cutoff() -> None:
    start = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    assertion = StructuredClaim(
        claim_id="news-assertion",
        player_id="p1",
        claim_type="starter_role",
        domain="role",
        latent_state="starter_security",
        direction=1.0,
        magnitude=1.0,
        provenance=_provenance(
            available_at=start,
            extractor_version="news-rules-v1",
            publisher_type="team_reporter",
        ),
        metadata={"source_claim_id": "source-news-1"},
    )
    retraction = StructuredClaim(
        claim_id="news-retraction",
        player_id="p1",
        claim_type="starter_role_retraction",
        domain="role",
        latent_state="starter_security",
        direction=0.0,
        magnitude=0.0,
        status="retracted",
        supersedes_claim_id=assertion.claim_id,
        provenance=_provenance(
            available_at=start + timedelta(hours=2),
            extractor_version="news-rules-v1",
            publisher_type="team_reporter",
        ),
        metadata={"source_claim_id": "source-news-2"},
    )
    official = StructuredClaim(
        claim_id="official-unrelated",
        player_id="p1",
        claim_type="official_game_designation",
        domain="availability",
        latent_state="availability",
        direction=-1.0,
        magnitude=1.0,
        provenance=_provenance(
            available_at=start,
            extractor_version="official-availability-adapter-v1",
            publisher_type="official_availability",
            evidence_class="OFFICIAL",
        ),
    )
    football = pd.DataFrame(
        {
            "player_id": ["p1", "p1"],
            "prediction_cutoff": [start + timedelta(hours=1), start + timedelta(hours=3)],
        }
    )

    attached = attach_canonical_structured_evidence(
        football,
        [assertion, retraction, official],
        family="structured_news",
    )

    assert attached.loc[0, "news_structured_snapshot_found"] == 1
    assert attached.loc[0, "news_structured_claim_count"] == 1
    assert attached.loc[0, "news_structured_starter_security_signal"] > 0.0
    assert attached.loc[1, "news_structured_snapshot_found"] == 0
    assert attached.loc[1, "news_structured_claim_count"] == 0
    assert attached.loc[1, "news_structured_starter_security_signal"] == 0.0


def test_research_attachment_keeps_official_evidence_research_only() -> None:
    cutoff = datetime(2026, 9, 9, 18, 0, tzinfo=UTC)
    official = StructuredClaim(
        claim_id="official-out",
        player_id="p1",
        claim_type="official_game_designation",
        domain="availability",
        latent_state="availability",
        direction=-1.0,
        magnitude=1.0,
        provenance=_provenance(
            available_at=cutoff - timedelta(hours=1),
            extractor_version="official-availability-adapter-v1",
            publisher_type="official_availability",
            evidence_class="OFFICIAL",
        ),
    )
    football = pd.DataFrame({"player_id": ["p1"], "prediction_cutoff": [cutoff]})

    attached = attach_canonical_structured_evidence(
        football,
        [official],
        family="official_availability",
    )

    assert attached.loc[0, "official_structured_snapshot_found"] == 1
    assert attached.loc[0, "official_structured_availability_signal"] < 0.0
    assert attached.loc[0, "official_structured_research_only"] == 1
    assert "production_feature_enabled" not in attached.columns
