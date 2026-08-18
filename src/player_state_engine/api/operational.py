from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from player_state_engine.api.app import create_app as create_base_app
from player_state_engine.api.draft_planner_routes import install_draft_planner_routes
from player_state_engine.api.draft_routes import install_draft_routes
from player_state_engine.api.game_intelligence_routes import install_game_intelligence_routes
from player_state_engine.api.ranking_routes import install_ranking_routes


def create_app(**kwargs: Any) -> FastAPI:
    """Create the operational Product API plus guarded research challenger surfaces."""
    operational_only = {
        "ranking_root",
        "game_intelligence_root",
        "game_intelligence_registry",
        "game_intelligence_benchmark_root",
    }
    base_kwargs = {key: value for key, value in kwargs.items() if key not in operational_only}
    app = create_base_app(**base_kwargs)
    draft_service = install_draft_routes(
        app,
        store_root=kwargs.get("store_root"),
        projections_path=kwargs.get("projections_path"),
    )
    install_draft_planner_routes(app, draft_service)
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
    app.version = "0.11.0"
    app.description = (
        f"{app.description} Live Draft War Room, ranking calibration, guarded game-intelligence "
        "simulation, expanding frozen replay, and state-conditioned opportunity research surfaces."
    )
    return app


app = create_app()
