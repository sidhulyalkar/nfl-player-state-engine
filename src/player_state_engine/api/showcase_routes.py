from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from player_state_engine.evaluation.weekly_showcase import WeeklyShowcaseStore


def install_showcase_routes(
    app: FastAPI,
    *,
    root: str | Path | None = None,
) -> WeeklyShowcaseStore:
    """Install evaluation-only routes with no production decision or promotion authority."""

    store = WeeklyShowcaseStore(root or os.getenv("PSE_MODEL_SHOWCASE_ROOT", "artifacts/evaluation/showcase"))

    @app.get("/v1/model/showcase")
    def showcase_index() -> dict[str, Any]:
        return store.index()

    @app.get("/v1/model/showcase/{season}")
    def showcase_season(season: int) -> dict[str, Any]:
        try:
            return store.season(season)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"No showcase artifacts for season {season}.") from exc

    @app.get("/v1/model/showcase/{season}/weeks/{week}")
    def showcase_week(
        season: int,
        week: int,
        position: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1, le=1000),
        artifact_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            payload = store.week(season, week, artifact_id=artifact_id)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=404,
                detail=f"No readable showcase artifact for {season} week {week}.",
            ) from exc
        players = payload["players"]
        if position:
            requested = position.strip().upper()
            players = [row for row in players if str(row.get("position") or "").upper() == requested]
        payload["players"] = players[:limit]
        payload["filters"] = {"position": position.upper() if position else None, "limit": limit}
        payload["authority"] = "evaluation_only"
        payload["may_change_production_decisions"] = False
        return payload

    return store
