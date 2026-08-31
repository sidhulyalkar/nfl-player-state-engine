from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from player_state_engine.api.league_connection_routes import install_league_connection_routes
from player_state_engine.product.store import LeagueSnapshotStore


class _DraftService:
    def __init__(self, store) -> None:
        self.store = store

    def list_leagues(self):
        return [
            {"league_id": "demo-league", "name": "Demo", "platform": "demo", "season": 2026},
            {"league_id": "123", "name": "Real", "platform": "sleeper", "season": 2026},
        ]


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("PSE_ESPN_S2", "server-secret")
    monkeypatch.setenv("PSE_ESPN_SWID", "{server-secret}")
    app = FastAPI()
    install_league_connection_routes(
        app,
        draft_service=_DraftService(LeagueSnapshotStore(tmp_path / "leagues")),
        portfolio_path=tmp_path / "portfolio.json",
    )
    return TestClient(app)


def test_connection_status_excludes_demo_and_never_returns_credentials(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.get("/v1/draft/connections")

    assert response.status_code == 200
    payload = response.json()
    assert payload["connected_league_count"] == 1
    assert payload["ignored_non_real_snapshot_count"] == 1
    assert payload["espn_private_auth_configured"] is True
    assert "server-secret" not in response.text


def test_portfolio_expectation_updates_local_contract(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.put(
        "/v1/draft/connections/expectation",
        json={"expected_league_count": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["expected_league_count"] == 3
    assert payload["connected_league_count"] == 1
    assert payload["missing_league_count"] == 2
    assert payload["complete"] is False


def test_connection_endpoint_rejects_browser_supplied_espn_cookies(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/v1/draft/connections",
        json={
            "platform": "espn",
            "league_id": "1427420",
            "season": 2026,
            "espn_s2": "browser-secret",
            "swid": "{browser-secret}",
        },
    )

    assert response.status_code == 400
    assert "browser-secret" not in response.text
    assert "server-side" in response.json()["detail"]
