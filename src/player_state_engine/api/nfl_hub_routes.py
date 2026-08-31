from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from player_state_engine.product.nfl_hub import load_nfl_hub_snapshot, refresh_nfl_hub

try:
    from fastapi import FastAPI, HTTPException, Query
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc

_REFRESH_LOCK = Lock()


def _age_seconds(snapshot: dict[str, Any], *, now: datetime) -> float | None:
    raw = snapshot.get("generated_at_utc")
    if not raw:
        return None
    try:
        generated = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=UTC)
    return max(0.0, (now - generated.astimezone(UTC)).total_seconds())


def install_nfl_hub_routes(
    app: FastAPI,
    *,
    root: str | Path | None = None,
    projections_path: str | Path | None = None,
) -> None:
    hub_root = Path(root or os.getenv("PSE_NFL_HUB_ROOT", "data/product/nfl_hub"))
    projection_location = (
        projections_path
        if projections_path is not None
        else os.getenv("PSE_NFL_HUB_PROJECTIONS_PATH", "")
    )

    @app.get("/v1/nfl/hub")
    def nfl_hub(
        season: int = Query(2026, ge=1999, le=2100),
        refresh: bool = False,
        max_age_minutes: float = Query(30.0, gt=0.0, le=1440.0),
    ) -> dict[str, Any]:
        warning: str | None = None
        refreshed = False
        if refresh:
            if not _REFRESH_LOCK.acquire(blocking=False):
                warning = "NFL Hub refresh already in progress; serving the latest cached snapshot."
            else:
                try:
                    try:
                        snapshot = refresh_nfl_hub(
                            season=int(season),
                            root=hub_root,
                            projections_path=projection_location,
                        )
                    except (OSError, RuntimeError, TypeError, ValueError) as exc:
                        warning = f"Live NFL Hub refresh failed; serving the last good snapshot: {exc}"
                        snapshot = load_nfl_hub_snapshot(hub_root)
                    else:
                        refreshed = True
                finally:
                    _REFRESH_LOCK.release()
        else:
            snapshot = load_nfl_hub_snapshot(hub_root)

        if snapshot is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "nfl_hub_unavailable",
                    "message": (
                        "No NFL Hub snapshot is available. Request refresh=true or run "
                        "scripts/refresh_nfl_hub.py."
                    ),
                    "refresh_warning": warning,
                },
            )
        if int(snapshot.get("season") or season) != int(season):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "nfl_hub_season_mismatch",
                    "message": (
                        f"Cached NFL Hub season={snapshot.get('season')} does not match requested "
                        f"season={season}; refresh the requested season."
                    ),
                },
            )

        now = datetime.now(UTC)
        age_seconds = _age_seconds(snapshot, now=now)
        stale_after = float(max_age_minutes) * 60.0
        stale = age_seconds is None or age_seconds > stale_after
        response = dict(snapshot)
        response.update(
            {
                "cache": {
                    "root": hub_root.as_posix(),
                    "refreshed_this_request": refreshed,
                    "snapshot_age_seconds": age_seconds,
                    "stale_after_seconds": stale_after,
                    "stale": stale,
                },
                "projection_context": {
                    "configured": bool(projection_location),
                    "path": str(projection_location) if projection_location else None,
                    "authority": "read_only_optional_context",
                },
                "refresh_warning": warning,
                "served_at_utc": now.isoformat(),
            }
        )
        if stale and response.get("status") == "READY":
            response["status"] = "STALE"
        return response
