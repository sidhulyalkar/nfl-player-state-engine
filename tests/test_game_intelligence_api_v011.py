from __future__ import annotations

import json

from fastapi.testclient import TestClient

from player_state_engine import __version__
from player_state_engine.api.operational import create_app


def test_benchmark_api_is_guarded_and_read_only(tmp_path) -> None:
    benchmark_root = tmp_path / "benchmark"
    benchmark_root.mkdir(parents=True)
    summary = {
        "aggregate_metrics": {"transition_decision_terminal": {"games": 250.0}},
        "diagnostics": {"protocol": "v016_terminal_family_eight_cell_expanding_weekly"},
        "promotion": {
            "promoted": False,
            "reasons": ["downstream evidence incomplete"],
            "production_projection_changed": False,
        },
    }
    (benchmark_root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    app = create_app(
        store_root=tmp_path / "leagues",
        projections_path=tmp_path / "missing.csv",
        ranking_root=tmp_path / "rankings",
        game_intelligence_root=tmp_path / "game-intelligence",
        game_intelligence_registry=tmp_path / "registry.json",
        game_intelligence_benchmark_root=benchmark_root,
    )
    assert app.version == __version__
    client = TestClient(app)

    status = client.get("/v1/research/game-intelligence/status")
    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload["model_family"] == "game_intelligence_v016_research"
    assert status_payload["benchmark_available"] is True
    assert status_payload["benchmark_protocol"] == "v016_terminal_family_eight_cell_expanding_weekly"
    assert status_payload["automatic_promotion"] is False

    response = client.get("/v1/research/game-intelligence/benchmark")
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["promotion"]["promoted"] is False
    assert payload["research_only"] is True
    assert payload["automatic_promotion"] is False
    assert payload["production_projection_changed"] is False


def test_benchmark_api_fails_closed_without_summary(tmp_path) -> None:
    app = create_app(
        store_root=tmp_path / "leagues",
        projections_path=tmp_path / "missing.csv",
        ranking_root=tmp_path / "rankings",
        game_intelligence_root=tmp_path / "game-intelligence",
        game_intelligence_registry=tmp_path / "registry.json",
        game_intelligence_benchmark_root=tmp_path / "missing-benchmark",
    )
    response = TestClient(app).get("/v1/research/game-intelligence/benchmark")
    assert response.status_code == 503
    assert "v0.16" in response.json()["detail"]
