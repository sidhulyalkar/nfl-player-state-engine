from __future__ import annotations

import os
from pathlib import Path

from player_state_engine.product.shadow_season import SHADOW_CHECKPOINTS, ShadowSeasonStore

try:
    from fastapi import FastAPI, HTTPException, Query
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


def install_shadow_season_routes(
    app: FastAPI,
    *,
    artifact_root: str | Path | None = None,
) -> None:
    """Expose the immutable live shadow ledger as a read-only research surface."""

    store = ShadowSeasonStore(
        artifact_root or os.getenv("PSE_SHADOW_SEASON_ROOT", "artifacts/shadow_season")
    )

    @app.get("/v1/model/shadow-season")
    def shadow_season_summary(
        season: int = Query(2026, ge=2020, le=2100),
    ) -> dict[str, object]:
        try:
            return store.summary(season=season)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/v1/model/shadow-season/health")
    def shadow_season_health(
        season: int = Query(2026, ge=2020, le=2100),
    ) -> dict[str, object]:
        return store.health(season=season)

    @app.get("/v1/model/shadow-season/snapshots")
    def shadow_season_snapshots(
        season: int = Query(2026, ge=2020, le=2100),
        week: int | None = Query(None, ge=1, le=18),
        checkpoint: str | None = Query(None),
    ) -> dict[str, object]:
        if checkpoint is not None and checkpoint.upper() not in SHADOW_CHECKPOINTS:
            raise HTTPException(
                status_code=422,
                detail=f"checkpoint must be one of {SHADOW_CHECKPOINTS}",
            )
        try:
            rows = store.snapshots(season=season)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if week is not None:
            rows = [row for row in rows if int(row.get("week", -1)) == week]
        if checkpoint is not None:
            rows = [
                row for row in rows if str(row.get("checkpoint")) == checkpoint.upper()
            ]
        return {
            "data_mode": "LIVE_SHADOW" if rows else "UNAVAILABLE",
            "authority": "research_observation_only",
            "count": len(rows),
            "snapshots": rows,
        }

    @app.get("/v1/model/shadow-season/snapshots/{snapshot_id}")
    def shadow_season_snapshot(snapshot_id: str) -> dict[str, object]:
        try:
            snapshot = store.load_snapshot(snapshot_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        settlement_path = store.settlement_path(snapshot_id)
        settlement = None
        if settlement_path.is_file():
            try:
                settlement = store._load(  # noqa: SLF001 - same read-only store contract.
                    settlement_path,
                    label="shadow settlement",
                )
            except (OSError, ValueError) as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "snapshot": snapshot,
            "settlement": settlement,
            "authority": {
                "snapshot": "immutable_live_shadow",
                "settlement": "evaluation_only",
                "promotion_is_automatic": False,
            },
        }
