from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from player_state_engine.api.operational import create_app
from player_state_engine.product.shadow_season import (
    ShadowSeasonStore,
    build_shadow_settlement,
    build_shadow_snapshot,
    normalize_production_forecasts,
)


def _seed(root) -> dict[str, object]:
    cutoff = datetime(2026, 9, 9, 18, 0, tzinfo=UTC)
    frame = normalize_production_forecasts(
        pd.DataFrame(
            {
                "player_id": ["p1"],
                "player_name": ["Player One"],
                "position": ["WR"],
                "team": ["SF"],
                "week_points_q10": [6.0],
                "week_points_q50": [12.0],
                "week_points_q90": [20.0],
            }
        )
    )
    snapshot = build_shadow_snapshot(
        frame,
        season=2026,
        week=1,
        checkpoint="WEDNESDAY",
        prediction_cutoff=cutoff,
        captured_at=cutoff + timedelta(minutes=2),
        sources=[{"name": "projections", "available_at": cutoff}],
    )
    store = ShadowSeasonStore(root)
    store.save_snapshot(snapshot)
    settlement = build_shadow_settlement(
        snapshot,
        pd.DataFrame({"player_id": ["p1"], "actual": [14.0]}),
    )
    store.save_settlement(settlement)
    return snapshot


def test_shadow_season_api_is_read_only_and_reports_settled_live_evidence(tmp_path) -> None:
    snapshot = _seed(tmp_path)
    client = TestClient(create_app(shadow_season_root=tmp_path))

    response = client.get("/v1/model/shadow-season", params={"season": 2026})
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "LIVE_SHADOW"
    assert payload["snapshot_count"] == 1
    assert payload["settlement_count"] == 1
    assert payload["health"]["integrity_verified"] is True
    assert payload["authority"]["promotion_is_automatic"] is False

    response = client.get(
        "/v1/model/shadow-season/snapshots",
        params={"season": 2026, "week": 1, "checkpoint": "WEDNESDAY"},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 1

    response = client.get(f"/v1/model/shadow-season/snapshots/{snapshot['snapshot_id']}")
    assert response.status_code == 200
    detail = response.json()
    assert detail["snapshot"]["content_sha256"] == snapshot["content_sha256"]
    assert detail["settlement"]["snapshot_content_sha256"] == snapshot["content_sha256"]
    assert detail["authority"]["promotion_is_automatic"] is False

    assert client.post("/v1/model/shadow-season", json={}).status_code == 405


def test_shadow_season_api_rejects_unknown_checkpoint(tmp_path) -> None:
    client = TestClient(create_app(shadow_season_root=tmp_path))
    response = client.get(
        "/v1/model/shadow-season/snapshots",
        params={"season": 2026, "checkpoint": "MONDAY"},
    )
    assert response.status_code == 422
