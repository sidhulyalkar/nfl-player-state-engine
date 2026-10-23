"""Metadata-only play inventory for the NFL BDB 2019 original 2017 tracking game.

Never exports player positions or trains a model. Use locally under applicable
source rights; an authentic hash does not establish redistribution permission.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from player_state_engine.product.bdb2019_source_qualification import (
    SOURCE_FILES,
    SOURCE_GAME_ID,
    file_identifiers,
)
from player_state_engine.product.gameday_legacy_tracking import _maybe_number

REQUIRED_COLUMNS = {"gameId", "playId", "frame.id", "nflId", "team", "event", "x", "y"}
OFFICIAL_SOURCE_ROWS = 316025
OFFICIAL_PLAY_COUNT = 177
OFFICIAL_UNDRAWABLE_ROWS = 1830
OFFICIAL_QUALITY_PLAYS = 60


def scan_bdb2019_play_catalog(
    csv_path: str | Path,
    *,
    license_acknowledged: bool = False,
    license_identifier: str = "",
    require_official_blob: bool = True,
    max_rows: int = 400_000,
) -> dict[str, Any]:
    """Stream a local tracking file into a bounded metadata-only play catalog.

    A noncanonical CSV can be used for isolated fixture tests by explicitly
    setting require_official_blob=False; it never receives official authority.
    """
    if not license_acknowledged or not license_identifier.strip():
        raise ValueError("Source terms must be explicitly reviewed and acknowledged.")
    if max_rows <= 0:
        raise ValueError("max_rows must be positive.")
    path = Path(csv_path)
    ids = file_identifiers(path)
    _, expected_blob, expected_size = SOURCE_FILES["tracking"]
    canonical = ids["git_blob_sha1"] == expected_blob and ids["bytes"] == expected_size
    if require_official_blob and not canonical:
        raise ValueError("Tracking CSV differs from pinned official NFL source bytes.")
    records: dict[str, dict[str, Any]] = {}
    all_rows = 0
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Missing tracking catalog columns: " + ", ".join(sorted(missing)))
        for row in reader:
            all_rows += 1
            if all_rows > max_rows:
                raise ValueError("Tracking catalog exceeded max_rows safety limit.")
            if row["gameId"] != SOURCE_GAME_ID:
                raise ValueError("The pinned single-game catalog cannot mix NFL game identifiers.")
            pid = row["playId"]
            if not pid or not pid.isdecimal():
                raise ValueError("Invalid play identity in tracking CSV.")
            try:
                fid = int(row["frame.id"])
            except (ValueError, TypeError) as exc:
                raise ValueError("Non-integer source frame identity.") from exc
            if fid < 1:
                raise ValueError("Source frame IDs must be positive.")
            entry = records.setdefault(pid, {
                "frames": set(), "players": set(), "ball_frames": set(),
                "seen": set(), "player_counts": Counter(),
                "events": defaultdict(set), "missing_xy": 0, "off_field": 0,
                "affected": set(), "rows": 0,
            })
            entry["rows"] += 1
            entry["frames"].add(fid)
            raw_id = (row["nflId"] or "").strip()
            player_id = "" if raw_id.lower() in {"na", "nan", "none", "null", ""} else raw_id
            entity_id = player_id or "__BALL__"
            ident = (fid, entity_id)
            if ident in entry["seen"]:
                raise ValueError("Duplicate source frame/entity tracking identity.")
            entry["seen"].add(ident)
            team = (row["team"] or "").strip().lower()
            if player_id:
                if team not in {"home", "away"}:
                    raise ValueError("A tracked player must carry home/away team metadata.")
                entry["players"].add(player_id)
                entry["player_counts"][fid] += 1
            else:
                if team not in {"ball", "football", ""}:
                    raise ValueError("Ball identity must not be assigned to a player team.")
                entry["ball_frames"].add(fid)
            event = (row["event"] or "").strip()
            if event and event.lower() not in {"na", "n/a", "nan", "null", "none"}:
                if len(event) > 128:
                    raise ValueError("Source event label exceeded maximum length.")
                entry["events"][event].add(fid)
            x, y = _maybe_number(row["x"]), _maybe_number(row["y"])
            if x is None or y is None:
                entry["missing_xy"] += 1
                entry["affected"].add(fid)
            elif x < 0 or x > 120 or y < 0 or y > 53.3:
                entry["off_field"] += 1
                entry["affected"].add(fid)

    plays: list[dict[str, Any]] = []
    for pid, r in records.items():
        frame_ids = sorted(r["frames"])
        span = frame_ids[-1] - frame_ids[0] + 1
        plays.append({
            "game_id": SOURCE_GAME_ID, "play_id": pid,
            "source_rows": r["rows"],
            "recorded_frames": len(frame_ids),
            "missing_frame_ids": span - len(frame_ids),
            "coverage_ratio": round(len(frame_ids) / span, 5),
            "first_frame_id": frame_ids[0],
            "last_frame_id": frame_ids[-1],
            "duration_seconds_nominal": round((frame_ids[-1] - frame_ids[0]) / 10, 2),
            "unique_players": len(r["players"]),
            "max_players_per_frame": max(r["player_counts"].values(), default=0),
            "ball_recorded_frames": len(r["ball_frames"]),
            "source_events": {event: sorted(frames) for event, frames in sorted(r["events"].items())},
            "unrenderable_position_rows": r["missing_xy"] + r["off_field"],
            "off_field_rows": r["off_field"],
            "missing_xy_rows": r["missing_xy"],
            "affected_source_frame_ids": sorted(r["affected"]),
        })
    plays.sort(key=lambda v: int(v["play_id"]))
    if canonical and (
        all_rows != OFFICIAL_SOURCE_ROWS
        or len(plays) != OFFICIAL_PLAY_COUNT
        or sum(p["unrenderable_position_rows"] for p in plays) != OFFICIAL_UNDRAWABLE_ROWS
        or sum(p["unrenderable_position_rows"] > 0 for p in plays) != OFFICIAL_QUALITY_PLAYS
    ):
        raise ValueError("Pinned official sample does not match independently audited catalog totals.")
    return {
        "schema_version": 1, "data_mode": "HISTORICAL_RESEARCH_METADATA_ONLY",
        "qualification_status": "OFFICIAL_TRACKING_BYTES_AUDITED_VIDEO_PENDING" if canonical
            else "SYNTHETIC_OR_NONCANONICAL_FIXTURE_ONLY",
        "game_id": SOURCE_GAME_ID,
        "source": "NFL Football Operations Big Data Bowl 2019 (2017 tracking)",
        "source_sha256": ids["sha256"], "source_bytes": ids["bytes"],
        "source_rows": all_rows, "play_count": len(plays),
        "positions_included": False, "source_video_alignment_verified": False,
        "license_declaration": license_identifier,
        "commercial_reuse_authorized": False, "model_training_authorized": False,
        "plays": plays,
    }


def write_play_catalog(catalog: dict[str, Any], output: str | Path) -> Path:
    """Serialize summary metrics only; never write original tracking rows."""
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(catalog, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return target
