from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from player_state_engine.intelligence.availability import build_official_availability_features
from player_state_engine.intelligence.news import claims_to_feature_snapshots, extract_news_claims
from player_state_engine.intelligence.schemas import PublicDocument


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
