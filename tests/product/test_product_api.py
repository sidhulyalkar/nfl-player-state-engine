from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from player_state_engine.api.app import create_app
from player_state_engine.product.demo import seed_product_demo
from tests.product.test_research import _write_research_artifacts


def _client(tmp_path: Path) -> TestClient:
    paths = seed_product_demo(tmp_path)
    benchmark, conformal, opportunity, historical_sources, team_context = _write_research_artifacts(
        tmp_path / "research"
    )
    return TestClient(
        create_app(
            store_root=tmp_path / "data/product/leagues",
            projections_path=paths["player_values"],
            schedules_path=paths["schedules"],
            benchmark_root=benchmark,
            conformal_root=conformal,
            opportunity_root=opportunity,
            historical_source_root=historical_sources,
            team_context_path=team_context,
            schedules_data_mode="SYNTHETIC_DEMO",
        )
    )


def test_player_board_and_needs_expose_ranks_and_trust_metadata(tmp_path: Path) -> None:
    client = _client(tmp_path)
    players_response = client.get("/v1/leagues/demo-league/players", params={"decision": "waiver"})
    assert players_response.status_code == 200
    players = players_response.json()
    assert [player["overall_rank"] for player in players] == list(range(1, len(players) + 1))
    assert players[0]["data_mode"] == "SYNTHETIC_DEMO"
    assert players[0]["model_version"] is None
    assert "model_version" in players[0]["missing_inputs"]
    assert players[0]["projection_artifact_file_modified_at"]
    assert "projection_artifact_updated_at" not in players[0]

    needs_response = client.get("/v1/leagues/demo-league/needs")
    assert needs_response.status_code == 200
    needs = needs_response.json()
    assert needs["data_mode"] == "SYNTHETIC_DEMO"
    assert needs["projection_artifact_file_modified_at"]
    assert needs["identity_coverage"]["coverage_rate"] == 1.0
    assert len(needs["needs"]) == 16
    assert all("strength_rank" in row and "need_rank" in row for row in needs["needs"])


def test_research_and_team_context_api_contracts(tmp_path: Path) -> None:
    client = _client(tmp_path)
    summary = client.get("/v1/research/summary")
    assert summary.status_code == 200
    assert summary.json()["artifacts"]["conformal"]["available"] is True

    predictions = client.get(
        "/v1/research/predictions",
        params={"season": 2025, "week": 18, "position": "QB", "limit": 1},
    )
    assert predictions.status_code == 200
    payload = predictions.json()
    assert payload["total_matches"] == 2
    assert payload["returned"] == 1
    assert payload["predictions"][0]["position_rank"] == 1

    context = client.get(
        "/v1/nfl/team-context",
        params={"season": 2025, "week": 2, "team": "AAA"},
    )
    assert context.status_code == 200
    context_payload = context.json()
    assert context_payload["total_matches"] == 1
    assert "team_plays_actual" not in context_payload["teams"][0]

    state = client.get("/v1/nfl/state", params={"season": 2026})
    assert state.status_code == 200
    assert state.json()["data_mode"] == "SYNTHETIC_DEMO"


def test_missing_research_prediction_and_team_context_artifacts_return_503(
    tmp_path: Path,
) -> None:
    paths = seed_product_demo(tmp_path)
    client = TestClient(
        create_app(
            store_root=tmp_path / "data/product/leagues",
            projections_path=paths["player_values"],
            schedules_path=paths["schedules"],
            benchmark_root=tmp_path / "missing",
            conformal_root=tmp_path / "missing",
            opportunity_root=tmp_path / "missing",
            team_context_path=tmp_path / "missing.parquet",
        )
    )
    assert client.get("/v1/research/predictions").status_code == 503
    assert client.get("/v1/nfl/team-context").status_code == 503


def test_unverified_schedule_provenance_fails_closed(tmp_path: Path) -> None:
    paths = seed_product_demo(tmp_path)
    client = TestClient(
        create_app(
            store_root=tmp_path / "data/product/leagues",
            projections_path=paths["player_values"],
            schedules_path=paths["schedules"],
        )
    )
    response = client.get("/v1/nfl/state", params={"season": 2026})
    assert response.status_code == 503
    assert "is not trusted" in response.json()["detail"]

    invalid_client = TestClient(
        create_app(
            store_root=tmp_path / "data/product/leagues",
            projections_path=paths["player_values"],
            schedules_path=paths["schedules"],
            schedules_data_mode="LIVE_OFFICIALS",
        )
    )
    invalid_response = invalid_client.get("/v1/nfl/state", params={"season": 2026})
    assert invalid_response.status_code == 503
    assert "LIVE_OFFICIALS" in invalid_response.json()["detail"]
