from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from player_state_engine.api.app import create_app as create_base_app
from player_state_engine.api.draft_planner_routes import install_draft_planner_routes
from player_state_engine.api.draft_routes import install_draft_routes
from player_state_engine.api.ranking_routes import install_ranking_routes


def create_app(**kwargs: Any) -> FastAPI:
    """Create the product API with live draft and ranking-calibration surfaces installed."""
    base_kwargs = {key: value for key, value in kwargs.items() if key != "ranking_root"}
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
    app.version = "0.9.0"
    app.description = (
        f"{app.description} Live Draft War Room, empirical market timing, roster "
        "counterfactuals, league-scoring provenance, external ranking calibration, "
        "and research two-turn lookahead."
    )
    return app


app = create_app()
