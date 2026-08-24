from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from player_state_engine.api.operational import create_app
from player_state_engine.intelligence.news import NewsClaim
from player_state_engine.intelligence.structured import (
    StructuredClaimLedger,
    structured_claim_from_news,
)


def _claim(
    *,
    claim_id: str,
    direction: float,
    source_url: str,
    collected_at: datetime,
):
    return structured_claim_from_news(
        NewsClaim(
            claim_id=claim_id,
            player_id="p1",
            claim_type="starter_role",
            direction=direction,
            magnitude=1.0,
            source_url=source_url,
            published_at_utc=collected_at - timedelta(minutes=30),
            collected_at_utc=collected_at,
            evidence_text="Point-in-time starter-role evidence.",
            extractor_confidence=0.9,
            source_reliability=0.9,
            document_id=f"doc-{claim_id}",
            evidence_class="REPORTED",
            latent_state="starter_security",
            decay_half_life_days=14.0,
        )
    )


def _seed(root) -> datetime:
    cutoff = datetime(2026, 9, 9, 18, 0, tzinfo=UTC)
    ledger = StructuredClaimLedger(root)
    ledger.save(
        _claim(
            claim_id="positive",
            direction=1.0,
            source_url="https://example.com/positive",
            collected_at=cutoff,
        )
    )
    ledger.save(
        _claim(
            claim_id="negative",
            direction=-1.0,
            source_url="https://example.com/negative",
            collected_at=cutoff,
        )
    )
    ledger.save(
        _claim(
            claim_id="future",
            direction=1.0,
            source_url="https://example.com/future",
            collected_at=cutoff + timedelta(hours=2),
        )
    )
    return cutoff


def _client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            structured_intelligence_root=tmp_path,
            intelligence_activation_registry=tmp_path / "activation.json",
        )
    )


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def test_structured_intelligence_api_is_read_only_and_point_in_time(tmp_path) -> None:
    cutoff = _seed(tmp_path)
    client = _client(tmp_path)

    response = client.get(
        "/v1/model/structured-intelligence",
        params={"as_of": cutoff.isoformat(), "player_id": "p1", "domain": "role"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "STRUCTURED_EVIDENCE"
    assert payload["authority"] == "research_evidence_only"
    assert payload["automatic_promotion"] is False
    assert payload["claim_count"] == 2
    assert payload["effective_claim_count"] == 2
    assert payload["state_count"] == 1
    assert payload["summary"]["max_conflict_score"] == 1.0
    assert payload["summary"]["production_feature_enabled"] is False
    assert payload["activation"]["enabled"] == []
    assert "structured_news" in payload["activation"]["disabled"]

    response = client.get(
        "/v1/model/structured-intelligence/claims",
        params={"as_of": cutoff.isoformat(), "player_id": "p1", "domain": "role"},
    )
    assert response.status_code == 200
    claims = response.json()
    assert claims["total_matches"] == 2
    assert claims["returned"] == 2
    assert all(row["effective_at_cutoff"] for row in claims["claims"])
    assert all(
        _parse_utc(row["provenance"]["available_at_utc"]) <= cutoff
        for row in claims["claims"]
    )

    health = client.get("/v1/model/structured-intelligence/health")
    assert health.status_code == 200
    assert health.json()["integrity_verified"] is True
    assert health.json()["claim_count"] == 3

    assert client.post("/v1/model/structured-intelligence", json={}).status_code == 405
    assert client.post("/v1/model/structured-intelligence/claims", json={}).status_code == 405


def test_structured_intelligence_api_validates_domain_and_cutoff(tmp_path) -> None:
    client = _client(tmp_path)

    invalid_domain = client.get(
        "/v1/model/structured-intelligence",
        params={"domain": "rumor_magic"},
    )
    assert invalid_domain.status_code == 422

    naive_cutoff = client.get(
        "/v1/model/structured-intelligence",
        params={"as_of": "2026-09-09T18:00:00"},
    )
    assert naive_cutoff.status_code == 422


def test_structured_intelligence_api_does_not_fabricate_empty_evidence(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get(
        "/v1/model/structured-intelligence",
        params={"as_of": "2026-09-09T18:00:00Z"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "UNAVAILABLE"
    assert payload["claim_count"] == 0
    assert payload["state_count"] == 0
    assert payload["states"] == []
    assert payload["summary"]["mean_conflict_score"] is None
    assert payload["summary"]["production_feature_enabled"] is False
