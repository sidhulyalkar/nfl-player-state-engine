from __future__ import annotations

from pathlib import Path

from player_state_engine.product.draft_launch_control import DraftLaunchControlService

try:
    from fastapi import FastAPI, HTTPException, Query
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


def install_draft_launch_routes(
    app: FastAPI,
    *,
    draft_service: object,
    connection_service: object,
    doctor_service: object,
    nfl_hub_root: str | Path | None = None,
    nfl_hub_projections_path: str | Path | None = None,
    special_teams_path: str | Path | None = None,
) -> DraftLaunchControlService:
    service = DraftLaunchControlService(
        draft_service=draft_service,
        connection_service=connection_service,
        doctor_service=doctor_service,
        nfl_hub_root=nfl_hub_root,
        nfl_hub_projections_path=nfl_hub_projections_path,
        special_teams_path=special_teams_path,
    )

    @app.get("/v1/draft/launch/status")
    def draft_launch_status() -> dict[str, object]:
        return service.status()

    @app.post("/v1/draft/launch/prepare")
    def prepare_draft(
        season: int = Query(default=2026, ge=2012, le=2100),
    ) -> dict[str, object]:
        try:
            return service.prepare(season=int(season)).as_dict()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return service
