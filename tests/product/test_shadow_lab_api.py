from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from player_state_engine.api.operational import create_app
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.product.demo import seed_product_demo
from tests.product.test_research import _write_research_artifacts


def _graph_root(root: Path) -> Path:
    graph = root / "graph"
    graph.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "player_id": "demo-001",
                "player_name": "Demo Player",
                "team": "DET",
                "position": "QB",
                "season": 2026,
                "week": 8,
                "q10": 12.0,
                "q50": 20.0,
                "q90": 29.0,
                "probability_active": 0.94,
                "role_change_probability": 0.18,
                "role_maturity": "MATURE",
                "regime_maturity": "MATURE",
            }
        ]
    ).to_parquet(graph / "player_state_graph_summaries.parquet", index=False)
    pd.DataFrame(
        [
            {
                "player_id": "demo-001",
                "team": "DET",
                "position": "QB",
                "season": 2026,
                "week": 8,
                "target_share_mean": 0.0,
                "carry_share_mean": 0.18,
            },
            {
                "player_id": "demo-teammate",
                "team": "DET",
                "position": "RB",
                "season": 2026,
                "week": 8,
                "target_share_mean": 0.16,
                "carry_share_mean": 0.54,
            },
        ]
    ).to_parquet(graph / "dynamic_role_states.parquet", index=False)
    league = LeagueConfig(scoring="ppr")
    (graph / "run_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "authority": "research_challenger_only",
                "forecast_horizon": "weekly",
                "league_contract": {
                    "teams": league.teams,
                    "scoring": league.scoring,
                    "scoring_weights": league.scoring_weights,
                    "roster_slots": league.roster_slots,
                },
            }
        ),
        encoding="utf-8",
    )
    return graph


def _client(tmp_path: Path, *, live_only: bool = False) -> TestClient:
    paths = seed_product_demo(tmp_path)
    store_root = tmp_path / "data/product/leagues"
    live_store_root = tmp_path / "data/product/live_leagues"
    live_store_root.mkdir(parents=True, exist_ok=True)
    if live_only:
        primary = store_root / "demo-league.json"
        (live_store_root / "my_connection_key.json").write_text(
            primary.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        primary.unlink()
    benchmark, conformal, opportunity, historical_sources, team_context = _write_research_artifacts(
        tmp_path / "research"
    )
    return TestClient(
        create_app(
            store_root=store_root,
            live_store_root=live_store_root,
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
            player_state_graph_root=_graph_root(tmp_path),
        )
    )


def test_player_shadow_route_preserves_authority_and_contract_checks(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/v1/leagues/demo-league/players/demo-001/shadow")
    assert response.status_code == 200
    payload = response.json()

    assert payload["data_mode"] == "RESEARCH_SHADOW"
    assert payload["graph_health"]["available"] is True
    assert payload["comparison"]["available"] is True
    assert payload["comparison"]["authority"]["production"] == "authoritative"
    assert payload["comparison"]["authority"]["challenger"] == "research_only"
    assert payload["comparison"]["authority"]["may_change_decision"] is False
    assert payload["comparison"]["scoring_contract"]["comparable"] is True
    assert payload["comparison"]["decision_comparable"] is True
    assert payload["opportunity"]["available"] is True


def test_scenario_route_is_sensitivity_only_and_never_overrides_production(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/v1/leagues/demo-league/players/demo-001/scenario",
        json={
            "role_multiplier": 1.15,
            "team_volume_multiplier": 1.05,
            "availability_probability": 0.98,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["semantics"] == "sensitivity_only_not_calibrated_forecast"
    assert payload["authority"]["may_override_production"] is False
    assert payload["production"]["scenario"]["q50"] > payload["production"]["baseline"]["q50"]

    invalid = client.post(
        "/v1/leagues/demo-league/players/demo-001/scenario",
        json={"role_multiplier": 1.8, "team_volume_multiplier": 1.0},
    )
    assert invalid.status_code == 422


def test_portfolio_endpoint_excludes_ambiguous_user_roster_instead_of_guessing(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/v1/portfolio/exposure")
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["source_stores"] == 2
    assert payload["summary"]["stored_leagues"] == 1
    assert payload["summary"]["resolved_user_rosters"] == 0
    assert payload["summary"]["unresolved_user_rosters"] == 1
    assert payload["players"] == []
    assert payload["authority"]["unresolved_leagues_are_excluded"] is True


def test_intelligence_routes_find_connection_key_named_live_snapshots(tmp_path: Path) -> None:
    client = _client(tmp_path, live_only=True)
    leagues = client.get("/v1/intelligence/leagues")
    board = client.get(
        "/v1/leagues/demo-league/intelligence/players",
        params={"decision": "trade"},
    )
    intelligence = client.get("/v1/leagues/demo-league/players/demo-001/intelligence")
    shadow = client.get("/v1/leagues/demo-league/players/demo-001/shadow")
    portfolio = client.get("/v1/portfolio/exposure")

    assert leagues.status_code == 200
    assert [row["league_id"] for row in leagues.json()] == ["demo-league"]
    assert board.status_code == 200
    assert any(row["player_id"] == "demo-001" for row in board.json())
    assert intelligence.status_code == 200
    assert intelligence.json()["player"]["player_id"] == "demo-001"
    assert shadow.status_code == 200
    assert shadow.json()["comparison"]["available"] is True
    assert portfolio.status_code == 200
    assert portfolio.json()["summary"]["stored_leagues"] == 1


def test_observatory_exposes_graph_health_without_granting_promotion(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/v1/model/observatory")
    assert response.status_code == 200
    payload = response.json()
    assert payload["player_state_graph"]["health"]["available"] is True
    assert payload["authority"]["player_state_graph"] == "research_challenger"
    assert payload["authority"]["promotion_is_automatic"] is False
