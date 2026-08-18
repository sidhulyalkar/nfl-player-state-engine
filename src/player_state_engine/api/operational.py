from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from player_state_engine.api.app import create_app as create_base_app
from player_state_engine.api.draft_routes import install_draft_routes


def create_app(**kwargs: Any) -> FastAPI:
    """Create the product API with the operational live Draft War Room installed."""
    app = create_base_app(**kwargs)
    install_draft_routes(
        app,
        store_root=kwargs.get("store_root"),
        projections_path=kwargs.get("projections_path"),
    )
    app.version = "0.8.0"
    app.description = (
        f"{app.description} Live Draft War Room, empirical market timing, "
        "and roster counterfactuals."
    )
    return app


app = create_app()
