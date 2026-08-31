from __future__ import annotations

from pathlib import Path

from player_state_engine.product.draft_day_doctor import DraftDayDoctorService
from player_state_engine.product.projection_artifact_source import ProjectionArtifactSource

try:
    from fastapi import FastAPI, Query
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


def install_draft_day_doctor_routes(
    app: FastAPI,
    *,
    projection_source: ProjectionArtifactSource,
    draft_service: object,
    nfl_hub_root: str | Path | None = None,
    special_teams_path: str | Path | None = None,
) -> DraftDayDoctorService:
    service = DraftDayDoctorService(
        projection_source=projection_source,
        draft_service=draft_service,
        nfl_hub_root=nfl_hub_root,
        special_teams_path=special_teams_path,
    )

    @app.get("/v1/draft/doctor")
    def draft_day_doctor(
        league_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        return service.report(league_id=league_id).as_dict()

    return service
