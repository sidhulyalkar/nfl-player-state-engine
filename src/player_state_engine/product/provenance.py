from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from player_state_engine.product.schemas import LeagueSnapshot


def artifact_metadata(path: str | Path, *, row_count: int | None = None) -> dict[str, object]:
    candidate = Path(path)
    available = candidate.is_file()
    return {
        "available": available,
        "path": candidate.as_posix(),
        "file_modified_at": (
            datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC).isoformat()
            if available
            else None
        ),
        "row_count": row_count,
    }


def frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return JSON-safe records, including nulls for pandas/NumPy missing values."""
    if frame.empty:
        return []
    clean = frame.replace([np.inf, -np.inf], np.nan)
    return json.loads(clean.to_json(orient="records", date_format="iso"))


def identity_coverage(snapshot: LeagueSnapshot) -> dict[str, object]:
    entries = [entry for roster in snapshot.rosters for entry in roster.players] + list(
        snapshot.free_agents
    )
    by_platform_id = {entry.platform_player_id: entry for entry in entries}
    unresolved = sorted(
        platform_id
        for platform_id, entry in by_platform_id.items()
        if not entry.canonical_player_id
    )
    total = len(by_platform_id)
    resolved = total - len(unresolved)
    return {
        "total_players": total,
        "resolved_players": resolved,
        "unresolved_players": len(unresolved),
        "coverage_rate": (resolved / total if total else None),
        "unresolved_player_ids": unresolved,
    }


def projection_metadata(
    frame: pd.DataFrame,
    path: str | Path,
    *,
    snapshot: LeagueSnapshot | None = None,
) -> dict[str, object]:
    data_modes = (
        sorted(frame["data_mode"].dropna().astype(str).unique().tolist())
        if "data_mode" in frame
        else []
    )
    if snapshot is not None and snapshot.identity.platform == "demo":
        data_mode = "SYNTHETIC_DEMO"
    elif len(data_modes) == 1:
        data_mode = data_modes[0]
    else:
        data_mode = "UNVERIFIED"

    model_versions = (
        sorted(frame["model_version"].dropna().astype(str).unique().tolist())
        if "model_version" in frame
        else []
    )
    missing_inputs = [
        field
        for field in ("model_version", "prediction_timestamp", "source_cutoff")
        if field not in frame or frame[field].isna().all()
    ]
    metadata = artifact_metadata(path, row_count=len(frame))
    return {
        "data_mode": data_mode,
        "model_version": model_versions[0] if len(model_versions) == 1 else None,
        "projection_artifact_file_modified_at": metadata["file_modified_at"],
        "missing_inputs": missing_inputs,
    }
