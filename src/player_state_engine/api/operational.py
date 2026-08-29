from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from player_state_engine.api.app import create_app as create_base_app
from player_state_engine.api.draft_planner_routes import install_draft_planner_routes
from player_state_engine.api.draft_reliability_routes import install_draft_reliability_routes
from player_state_engine.api.draft_routes import install_draft_routes
from player_state_engine.api.evidence_routes import install_evidence_routes
from player_state_engine.api.game_intelligence_routes import install_game_intelligence_routes
from player_state_engine.api.intelligence_routes import install_intelligence_routes
from player_state_engine.api.nfl_hub_routes import install_nfl_hub_routes
from player_state_engine.api.ranking_routes import install_ranking_routes
from player_state_engine.api.shadow_season_routes import install_shadow_season_routes
from player_state_engine.api.structured_intelligence_routes import (
    install_structured_intelligence_routes,
)


def create_app(**kwargs: Any) -> FastAPI:
    """Create the operational Product API plus guarded research challenger surfaces."""
    operational_only = {
        "ranking_root",
        "game_intelligence_root",
        "game_intelligence_registry",
        "game_intelligence_benchmark_root",
        "player_state_graph_root",
        "live_store_root",
        "evidence_factory_root",
        "shadow_season_root",
        "structured_intelligence_root",
        "intelligence_activation_registry",
        "nfl_hub_root",
    }
    base_kwargs = {key: value for key, value in kwargs.items() if key not in operational_only}
    app = create_base_app(**base_kwargs)
    draft_service = install_draft_routes(
        app,
        store_root=kwargs.get("store_root"),
        projections_path=kwargs.get("projections_path"),
    )
    install_draft_planner_routes(app, draft_service)
    install_draft_reliability_routes(app, draft_service)
    install_intelligence_routes(
        app,
        store_root=kwargs.get("store_root"),
        live_store_root=kwargs.get("live_store_root"),
        projections_path=kwargs.get("projections_path"),
        benchmark_root=kwargs.get("benchmark_root"),
        conformal_root=kwargs.get("conformal_root"),
        opportunity_root=kwargs.get("opportunity_root"),
        historical_source_root=kwargs.get("historical_source_root"),
        player_state_graph_root=kwargs.get("player_state_graph_root"),
    )
    install_nfl_hub_routes(
        app,
        root=kwargs.get("nfl_hub_root"),
        projections_path=kwargs.get("projections_path"),
    )
    install_evidence_routes(
        app,
        evidence_factory_root=kwargs.get("evidence_factory_root"),
    )
    install_shadow_season_routes(
        app,
        artifact_root=kwargs.get("shadow_season_root"),
    )
    install_structured_intelligence_routes(
        app,
        artifact_root=kwargs.get("structured_intelligence_root"),
        activation_registry_path=kwargs.get("intelligence_activation_registry"),
    )
    install_ranking_routes(
        app,
        store_root=kwargs.get("store_root"),
        projections_path=kwargs.get("projections_path"),
        ranking_root=kwargs.get("ranking_root"),
    )
    install_game_intelligence_routes(
        app,
        artifact_root=kwargs.get("game_intelligence_root"),
        registry_path=kwargs.get("game_intelligence_registry"),
        benchmark_root=kwargs.get("game_intelligence_benchmark_root"),
    )
    app.version = "0.16.0"
    app.description = (
        f"{app.description} Live Draft War Room, NFL Hub state-change intelligence, player "
        "intelligence, cross-league portfolio exposure, Player State Graph shadow comparison "
        "and sensitivity, frozen Evidence Factory, immutable 2026 live shadow-season evidence, "
        "structured intelligence evidence ledger, model observatory, ranking calibration, guarded "
        "draft reliability, guarded game-intelligence simulation, expanding frozen replay, "
        "factorial attribution, simulated-state opportunity, drive-volume, possession-transition, "
        "fourth-down decision, and terminal-family research surfaces."
    )
    return app


app = create_app()
