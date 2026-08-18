from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field

from player_state_engine.api.draft_routes import DraftBoardService
from player_state_engine.fantasy.draft_planner import plan_two_turn_draft

try:
    from fastapi import FastAPI, HTTPException
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


class DraftPlanRequest(BaseModel):
    roster_id: str
    player_ids: list[str] = Field(min_length=2, max_length=5)
    draft_slot: int | None = Field(default=None, ge=1)
    total_rounds: int | None = Field(default=None, ge=1)
    refresh: bool = False
    force_refresh: bool = False
    simulations: int = Field(default=2000, ge=200, le=20000)


def install_draft_planner_routes(app: FastAPI, service: DraftBoardService) -> None:
    @app.post("/v1/leagues/{league_id}/draft/plan")
    def draft_two_turn_plan(
        league_id: str, request: DraftPlanRequest
    ) -> dict[str, object]:
        try:
            payload = service.board(
                league_id,
                request.roster_id,
                draft_slot=request.draft_slot,
                total_rounds=request.total_rounds,
                refresh=request.refresh,
                force_refresh=request.force_refresh,
                limit=1000,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        board = pd.DataFrame(payload.get("board") or [])
        if board.empty:
            raise HTTPException(status_code=422, detail="Live draft board is empty.")
        try:
            plans = plan_two_turn_draft(
                board,
                request.player_ids,
                value_column="decision_specific_score",
                simulations=request.simulations,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "league_id": league_id,
            "roster_id": request.roster_id,
            "draft_state": payload.get("draft_state"),
            "plans": [plan.to_dict() for plan in plans],
            "model_source": "two_turn_survival_lookahead_research_v1",
            "promoted": False,
            "caveats": [
                "Research challenger only: production draft actions still use the validated live board.",
                "Intervening opponent rosters are not yet re-optimized in every simulated branch.",
                "Promotion requires frozen historical room-state replay and roster-utility improvement.",
            ],
        }
