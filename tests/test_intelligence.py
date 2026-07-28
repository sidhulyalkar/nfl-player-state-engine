from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from player_state_engine.features.intelligence import attach_point_in_time_intelligence
from player_state_engine.intelligence.availability import build_availability_features
from player_state_engine.intelligence.persona import (
    build_persona_snapshots,
    snapshots_to_feature_frame,
)
from player_state_engine.intelligence.schemas import PublicDocument


def test_persona_extraction_is_evidence_backed() -> None:
    now = datetime(2026, 9, 10, tzinfo=UTC)
    documents = [
        PublicDocument(
            document_id="d1",
            player_id="p1",
            platform="x",
            source_url="https://example.com/1",
            text="Back to training, studying film, and ready to compete with my teammates.",
            authored_at_utc=now - timedelta(days=2),
        ),
        PublicDocument(
            document_id="d2",
            player_id="p1",
            platform="threads",
            source_url="https://example.com/2",
            text="Recovery work done. Ready for the matchup and whatever role the team needs.",
            authored_at_utc=now - timedelta(days=1),
        ),
    ]
    snapshots = build_persona_snapshots(documents, as_of_utc=now)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.persona_training_focus > 0
    assert snapshot.persona_recovery_focus > 0
    assert snapshot.persona_evidence_strength > 0
    assert snapshot.evidence
    frame = snapshots_to_feature_frame(snapshots)
    assert "persona_matchup_specificity" in frame


def test_intelligence_join_uses_only_prior_snapshot() -> None:
    football = pd.DataFrame(
        {
            "player_id": ["p1", "p1"],
            "gameday": ["2026-09-10T20:00:00Z", "2026-09-17T20:00:00Z"],
            "season": [2026, 2026],
            "week": [1, 2],
        }
    )
    intelligence = pd.DataFrame(
        {
            "player_id": ["p1", "p1", "p1"],
            "as_of_utc": [
                "2026-09-10T18:00:00Z",
                "2026-09-10T21:00:00Z",
                "2026-09-17T18:00:00Z",
            ],
            "persona_training_focus": [0.2, 0.9, 0.4],
        }
    )
    joined = attach_point_in_time_intelligence(football, intelligence, safety_lag_hours=1)
    assert joined.loc[0, "persona_training_focus"] == 0.2
    assert joined.loc[1, "persona_training_focus"] == 0.4


def test_availability_features_are_bounded() -> None:
    evidence = pd.DataFrame(
        {
            "player_id": ["p1", "p2"],
            "observed_at_utc": ["2026-09-10T10:00:00Z", "2026-09-10T10:00:00Z"],
            "practice_status": ["limited", "did_not_participate"],
            "game_status": ["questionable", "out"],
            "source_reliability": [1.0, 1.0],
        }
    )
    features = build_availability_features(evidence)
    assert features["availability_expected_active"].between(0, 1).all()
    assert features.loc[features["player_id"] == "p2", "availability_is_out"].iloc[0] == 1


def test_multiple_intelligence_families_keep_separate_cutoffs() -> None:
    from player_state_engine.features.intelligence import attach_intelligence_families

    football = pd.DataFrame({"player_id": ["p1"], "gameday": ["2026-09-10T20:00:00Z"]})
    availability = pd.DataFrame(
        {
            "player_id": ["p1"],
            "as_of_utc": ["2026-09-10T18:00:00Z"],
            "availability_expected_active": [0.7],
        }
    )
    news = pd.DataFrame(
        {"player_id": ["p1"], "as_of_utc": ["2026-09-10T17:00:00Z"], "news_starter_role": [1.0]}
    )
    joined = attach_intelligence_families(football, {"availability": availability, "news": news})
    assert joined.loc[0, "availability_expected_active"] == 0.7
    assert joined.loc[0, "news_starter_role"] == 1.0
    assert joined.loc[0, "availability_snapshot_found"] == 1
    assert joined.loc[0, "news_snapshot_found"] == 1
