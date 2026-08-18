from __future__ import annotations

from datetime import UTC, datetime, timedelta

from player_state_engine.intelligence.news import (
    claims_to_feature_snapshots,
    extract_news_claims,
)
from player_state_engine.intelligence.schemas import PublicDocument


def test_official_status_has_more_authority_than_speculation() -> None:
    now = datetime(2026, 8, 17, 18, 0, tzinfo=UTC)
    official = PublicDocument(
        document_id="official",
        player_id="p1",
        platform="nfl_official",
        source_url="https://example.test/official",
        text="The team announced that Player One returned to practice and was a full participant.",
        authored_at_utc=now,
        collected_at_utc=now,
    )
    speculative = PublicDocument(
        document_id="spec",
        player_id="p1",
        platform="fantasy_analysis",
        source_url="https://example.test/spec",
        text="Player One might have more routes and could possibly earn more targets.",
        authored_at_utc=now - timedelta(hours=1),
        collected_at_utc=now,
    )
    claims = extract_news_claims([official, speculative])
    by_document = {claim.document_id: claim for claim in claims}
    assert by_document["official"].evidence_class == "OFFICIAL"
    assert by_document["spec"].evidence_class == "SPECULATION"
    assert by_document["official"].extractor_confidence > by_document["spec"].extractor_confidence

    snapshots = claims_to_feature_snapshots(claims)
    latest = snapshots.sort_values("as_of_utc").iloc[-1]
    assert latest.news_high_authority_claim_count >= 1
    assert latest.news_speculation_count >= 1
    assert "evidence_state_availability" in snapshots.columns


def test_first_team_reps_map_to_starter_security() -> None:
    now = datetime(2026, 8, 17, 18, 0, tzinfo=UTC)
    doc = PublicDocument(
        document_id="practice",
        player_id="p2",
        platform="beat_reporter",
        source_url="https://example.test/practice",
        author_handle="reporter",
        text="At practice we observed Player Two working with the ones and taking first-team reps in 11-on-11 drills.",
        authored_at_utc=now,
        collected_at_utc=now,
    )
    claim = extract_news_claims([doc])[0]
    assert claim.claim_type == "first_team_reps"
    assert claim.latent_state == "starter_security"
    assert claim.evidence_class == "DIRECT_OBSERVATION"
