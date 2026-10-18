"""Read-only Sunday board API. Explicit refresh, bounded public source polling."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from player_state_engine.product.sunday_board import build_sunday_board


def install_sunday_board_routes(app: FastAPI) -> None:
    root = Path(os.getenv("PSE_SUNDAY_BOARD_ROOT", "data/product/sunday_board"))

    @app.get("/v1/gameday/sunday-board")
    def sunday_board(
        season: int = Query(2026, ge=1999, le=2100),
        week: int | None = Query(None, ge=1, le=18),
        refresh: bool = False,
    ) -> dict[str, Any]:
        try:
            return build_sunday_board(
                root=root,
                season=season,
                week=week,
                refresh=refresh,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
