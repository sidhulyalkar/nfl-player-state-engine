from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from player_state_engine.api.operational import create_app
from player_state_engine.product.demo import seed_product_demo
from player_state_engine.product.research import ResearchArtifacts
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
            ranking_root=tmp_path / "missing-ranking",
            game_intelligence_root=tmp_path / "missing-game-intelligence",
        )
    )


def test_player_intelligence_exposes_one_league_specific_truth_surface(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/v1/leagues/demo-league/players/demo-001/intelligence")
    assert response.status_code == 200
    payload = response.json()

    assert payload["player"]["player_id"] == "demo-001"
    assert payload["player"]["owner_roster_id"] == "1"
    assert payload["projection"]["q10"] <= payload["projection"]["q50"]
    assert payload["projection"]["q50"] <= payload["projection"]["q90"]
    assert payload["projection"]["interval_width"] > 0
    assert {row["decision"] for row in payload["decision_matrix"]} == {
        "start_sit",
        "waiver",
        "trade",
        "draft",
        "stash",
        "dynasty",
    }
    assert payload["authority"]["production_projection_authoritative"] is True
    assert payload["authority"]["player_state_graph_authority"] == "research_only"
    assert payload["trust"]["data_mode"] == "SYNTHETIC_DEMO"


def test_model_observatory_exposes_calibration_without_promoting_research(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/v1/model/observatory")
    assert response.status_code == 200
    payload = response.json()

    assert payload["authority"]["production_champion"] == "direct_player_quantile_model"
    assert payload["authority"]["player_state_graph"] == "research_challenger"
    assert payload["authority"]["promotion_is_automatic"] is False
    assert payload["artifact_health"]["available"] == payload["artifact_health"]["total"]
    overall = payload["diagnostics"]["overall"]
    assert overall["rows"] == 3
    assert 0.0 <= overall["empirical_80_coverage"] <= 1.0
    assert overall["q50_mae"] >= 0.0
    assert overall["mean_interval_width"] > 0.0


def test_research_diagnostics_and_player_history_are_filterable(tmp_path: Path) -> None:
    benchmark, conformal, opportunity, historical_sources, _ = _write_research_artifacts(
        tmp_path / "research"
    )
    research = ResearchArtifacts(
        benchmark_root=benchmark,
        conformal_root=conformal,
        opportunity_root=opportunity,
        historical_source_root=historical_sources,
    )

    diagnostics = research.diagnostics(minimum_rows=2)
    assert diagnostics["authority"] == "diagnostic_only"
    assert diagnostics["target_coverage"] == pytest.approx(0.80)
    assert {row["position"] for row in diagnostics["by_position"]} == {"QB"}
    assert diagnostics["by_position"][0]["rows"] == 2

    history = research.predictions(player_id="qb-a", limit=100)
    assert history["total_matches"] == 1
    assert history["filters"]["player_id"] == "qb-a"
    assert history["predictions"][0]["player_name"] == "QB A"
