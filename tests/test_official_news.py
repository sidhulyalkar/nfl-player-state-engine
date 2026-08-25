from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from player_state_engine.intelligence.availability import build_official_availability_features
from player_state_engine.intelligence.news import claims_to_feature_snapshots, extract_news_claims
from player_state_engine.intelligence.schemas import PublicDocument


def _official_document(*, document_id: str, text: str, player_name: str | None = None) -> PublicDocument:
    return PublicDocument(
        document_id=document_id,
        player_id="p1",
        player_name=player_name,
        platform="team_official",
        source_url=f"https://example.com/{document_id}",
        text=text,
        authored_at_utc=datetime(2026, 9, 9, 16, 0, tzinfo=UTC),
        collected_at_utc=datetime(2026, 9, 9, 17, 0, tzinfo=UTC),
        metadata={"source_reliability": 0.95},
    )


def test_official_availability_preserves_evidence_families() -> None:
    evidence = pd.DataFrame(
        [
            {
                "player_id": "p1",
                "observed_at_utc": "2025-09-10T18:00:00Z",
                "event_type": "practice_participation",
                "practice_status": "limited",
            },
            {
                "player_id": "p1",
                "observed_at_utc": "2025-09-12T18:00:00Z",
                "event_type": "game_designation",
                "game_status": "questionable",
            },
            {
                "player_id": "p1",
                "observed_at_utc": "2025-09-14T15:00:00Z",
                "event_type": "coach_workload",
                "expected_workload_fraction": 0.55,
            },
        ]
    )
    features = build_official_availability_features(evidence)
    latest = features.iloc[-1]
    assert latest["availability_expected_active"] < 1.0
    assert latest["availability_expected_workload_fraction"] == 0.55
    assert latest["availability_official_evidence_count"] == 3


def test_news_claims_retain_provenance_and_build_features() -> None:
    document = PublicDocument(
        document_id="d1",
        player_id="p1",
        platform="public_web",
        source_url="https://example.com/story",
        text="The head coach said the player will start, but will not have a full workload.",
        authored_at_utc=datetime(2025, 9, 12, tzinfo=UTC),
        collected_at_utc=datetime(2025, 9, 12, 1, tzinfo=UTC),
    )
    claims = extract_news_claims([document])
    claim_types = {claim.claim_type for claim in claims}
    assert {"starter_role", "workload_limit"}.issubset(claim_types)
    assert all(claim.evidence_text and claim.source_url for claim in claims)
    features = claims_to_feature_snapshots(claims)
    assert features.iloc[-1]["news_starter_role"] > 0
    assert features.iloc[-1]["news_workload_limit"] < 0


def test_starter_role_accepts_explicit_player_reference() -> None:
    document = _official_document(
        document_id="starter-player",
        text="The team named the player the starter for Week 1.",
        player_name="Player One",
    )
    claims = extract_news_claims([document])
    starters = [claim for claim in claims if claim.claim_type == "starter_role"]
    assert len(starters) == 1
    assert starters[0].evidence_class == "OFFICIAL"
    assert starters[0].direction == 1.0


def test_starter_role_accepts_exact_known_player_name() -> None:
    document = _official_document(
        document_id="starter-name",
        text="The team named Player One the starter for Week 1.",
        player_name="Player One",
    )
    claims = extract_news_claims([document])
    starters = [claim for claim in claims if claim.claim_type == "starter_role"]
    assert len(starters) == 1
    assert starters[0].evidence_class == "OFFICIAL"


def test_starter_role_does_not_accept_arbitrary_named_phrase() -> None:
    document = _official_document(
        document_id="starter-false-positive",
        text="The club named the stadium starter package after a sponsor.",
        player_name="Player One",
    )
    claims = extract_news_claims([document])
    assert all(claim.claim_type != "starter_role" for claim in claims)
