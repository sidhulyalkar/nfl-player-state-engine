"""Research-only historical Big Data Bowl 2025 tracking adapter.

This module consumes a local CSV supplied by an authorized user. It does not
download or scrape Next Gen Stats, and its output is never a live-game feed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = {"gameId", "playId", "nflId", "frameId", "x", "y"}
FIELD_LENGTH_YARDS = 120.0
FIELD_WIDTH_YARDS = 53.3


def _optional_number(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Tracking data contains a non-finite number.")
    return number


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_bdb_2025_tracking(
    csv_path: str | Path,
    *,
    game_id: str,
    play_id: str,
    license_acknowledged: bool = False,
    license_identifier: str = "",
    possession_team: str | None = None,
    max_selected_rows: int = 25000,
) -> dict[str, Any]:
    """Normalize one 2025 BDB play's 10-Hz tracking, preserving evidence boundaries.

    Inputs are historical research data, NOT suitable for licensed commercial
    redistribution. Contest/provider rights must be confirmed by the caller.
    """
    if not license_acknowledged or not license_identifier.strip():
        raise ValueError(
            "Explicit source rights acknowledgment and license identifier are required."
        )
    if not game_id.strip() or not play_id.strip():
        raise ValueError("Both game_id and play_id are required.")
    if max_selected_rows < 1:
        raise ValueError("max_selected_rows must be positive.")

    path = Path(csv_path)
    rows_by_frame: dict[int, list[dict[str, Any]]] = {}
    ids_by_frame: dict[int, set[str]] = {}
    events_by_frame: dict[int, set[str]] = {}
    first_direction: str | None = None
    matched_rows = 0

    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        names = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - names
        if missing:
            raise ValueError("Missing required Big Data Bowl 2025 columns: " + ", ".join(sorted(missing)))

        for raw in reader:
            if raw["gameId"] != game_id or raw["playId"] != play_id:
                continue
            matched_rows += 1
            if matched_rows > max_selected_rows:
                raise ValueError("Selected play exceeded max_selected_rows safety limit.")
            frame = int(raw["frameId"])
            if frame < 1:
                raise ValueError("frameId must be positive.")
            player_id = (raw.get("nflId") or "").strip()
            entity_key = player_id if player_id else "__BALL__"
            seen = ids_by_frame.setdefault(frame, set())
            if entity_key in seen:
                raise ValueError("Duplicate frame/entity identity in source tracking.")
            seen.add(entity_key)

            x = _optional_number(raw["x"])
            y = _optional_number(raw["y"])
            if x is None or y is None or not (0 <= x <= FIELD_LENGTH_YARDS) or not (0 <= y <= FIELD_WIDTH_YARDS):
                raise ValueError("Out-of-bounds or missing tracking x/y coordinate.")

            direction = (raw.get("playDirection") or "").strip().lower()
            if direction:
                if direction not in {"left", "right"}:
                    raise ValueError("Unknown playDirection in source tracking.")
                if first_direction is not None and direction != first_direction:
                    raise ValueError("Inconsistent playDirection within selected play.")
                first_direction = direction
            club = (raw.get("club") or "").strip() or None
            side = (
                "offense" if possession_team and club == possession_team
                else "defense" if possession_team and club and club != possession_team
                else None
            )
            entry = {
                "nfl_id": player_id or None,
                "is_ball": not bool(player_id),
                "team": club,
                "side": side,
                "name": (raw.get("displayName") or "").strip() or None,
                "jersey": (raw.get("jerseyNumber") or "").strip() or None,
                "x": x,
                "y": y,
                "z": None,  # Source x/y alone does not establish ball height.
                "speed_yards_per_s": _optional_number(raw.get("s")),
                "acceleration_yards_per_s2": _optional_number(raw.get("a")),
                "orientation_deg": _optional_number(raw.get("o")),
                "movement_dir_deg": _optional_number(raw.get("dir")),
                "observed": True,
            }
            rows_by_frame.setdefault(frame, []).append(entry)
            event = (raw.get("event") or "").strip()
            if event and event.lower() not in {"none", "nan"}:
                events_by_frame.setdefault(frame, set()).add(event)

    if not rows_by_frame:
        raise ValueError("No tracking rows matched the requested game_id/play_id.")
    frame_ids = sorted(rows_by_frame)
    first_frame = frame_ids[0]
    expected_frame_count = frame_ids[-1] - first_frame + 1
    missing_frames = expected_frame_count - len(frame_ids)

    frames = [
        {
            "frame_id": frame,
            "t_seconds_nominal": (frame - first_frame) / 10.0,
            "players": [r for r in rows_by_frame[frame] if not r["is_ball"]],
            "ball": next((r for r in rows_by_frame[frame] if r["is_ball"]), None),
            "events": sorted(events_by_frame.get(frame, set())),
        }
        for frame in frame_ids
    ]
    return {
        "schema_version": 1,
        "data_mode": "HISTORICAL_RESEARCH",
        "tracking_fidelity": "RECORDED_FRAMES",
        "source": "NFL Big Data Bowl 2025 local user-supplied CSV",
        "source_license_identifier": license_identifier,
        "rights_attested_by_caller": True,
        "commercial_reuse_authorized": False,
        "model_training_authorized": False,
        "production_model_promoted": False,
        "game_id": game_id,
        "play_id": play_id,
        "possession_team": possession_team,
        "play_direction": first_direction,
        "coordinate_system": {"x_yards": [0, 120], "y_yards": [0, 53.3], "z_available": False},
        "sample_rate_hz_nominal": 10,
        "frame_count": len(frames),
        "missing_frame_count": missing_frames,
        "frame_coverage": len(frames) / expected_frame_count,
        "rows": matched_rows,
        "source_file_sha256": _file_sha256(path),
        "frames": frames,
    }


def write_replay_json(replay: dict[str, Any], output_path: str | Path) -> Path:
    """Save a normalized research replay. Do not place copyrighted frames in git."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(replay, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path
