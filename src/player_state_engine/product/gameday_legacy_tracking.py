"""Normalize the NFL Football Operations Big Data Bowl 2019 sample tracking.

The official NFL open GitHub repository contains one 2017 game's tracking CSV,
using frame.id and home/away labels. Public access does not necessarily confer
commercial redistribution rights; caller must review applicable source terms.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from player_state_engine.product.gameday_tracking import (
    FIELD_LENGTH_YARDS,
    FIELD_WIDTH_YARDS,
    _file_sha256,
    _optional_number,
)

REQUIRED_COLUMNS = {"gameId", "playId", "nflId", "frame.id", "x", "y", "team"}
SOURCE = "NFL Football Operations Big Data Bowl 2019 example (2017 tracking)"


def _maybe_number(value: str | None) -> float | None:
    if value is None or str(value).strip().lower() in {"", "na", "n/a", "nan", "null", "none"}:
        return None
    return _optional_number(value)


def import_bdb_2019_example(
    csv_path: str | Path,
    *,
    game_id: str,
    play_id: str,
    license_acknowledged: bool = False,
    license_identifier: str = "",
    offense_side: str | None = None,
    max_selected_rows: int = 25000,
    position_policy: str = "strict",
) -> dict[str, Any]:
    """Normalize one historic play, preserving source frame gaps and roles.

    offense_side may be home or away, but must be verified via separate plays
    and games files; NEVER infer team possession from on-field coordinates.

    strict rejects any missing/out-of-field source coordinate. For public
    historical plays where players legitimately leave the field, the explicit
    omit_off_field_with_audit policy preserves the frame and all source events
    but excludes unusable locations from on-field rendering, with counts.
    """
    if not license_acknowledged or not license_identifier.strip():
        raise ValueError("Explicit source rights acknowledgment and license identifier are required.")
    if not game_id.strip() or not play_id.strip():
        raise ValueError("game_id and play_id are required.")
    if offense_side not in {None, "home", "away"}:
        raise ValueError("offense_side must be home or away, sourced from play metadata.")
    if max_selected_rows < 1:
        raise ValueError("max_selected_rows must be positive.")
    if position_policy not in {"strict", "omit_off_field_with_audit"}:
        raise ValueError("Unknown recorded-position policy.")

    path = Path(csv_path)
    frame_entities: dict[int, list[dict[str, Any]]] = {}
    seen_in_frame: dict[int, set[str]] = {}
    frame_events: dict[int, set[str]] = {}
    matched = 0
    omitted_missing_positions = 0
    omitted_off_field_positions = 0
    omitted_frame_ids: set[int] = set()

    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Missing BDB 2019 example columns: " + ", ".join(sorted(missing)))

        for row in reader:
            if row["gameId"] != game_id or row["playId"] != play_id:
                continue
            matched += 1
            if matched > max_selected_rows:
                raise ValueError("Selected play exceeded max_selected_rows safety limit.")
            try:
                frame_id = int(row["frame.id"])
            except ValueError as exc:
                raise ValueError("Invalid frame.id") from exc
            if frame_id < 1:
                raise ValueError("frame.id must be positive.")
            ident = (row.get("nflId") or "").strip()
            if ident.lower() in {"na", "nan", "none", "null"}:
                ident = ""
            unique = ident or "__BALL__"
            frame_seen = seen_in_frame.setdefault(frame_id, set())
            if unique in frame_seen:
                raise ValueError("Duplicate identity within a recorded frame.")
            frame_seen.add(unique)
            # Preserve source frames/events even if an entity has no valid
            # on-field position. Never reconstruct or boundary-clamp its x/y.
            frame_entities.setdefault(frame_id, [])
            event = (row.get("event") or "").strip()
            if event and event.lower() not in {"na", "n/a", "nan", "none", "null"}:
                frame_events.setdefault(frame_id, set()).add(event)

            x = _maybe_number(row["x"])
            y = _maybe_number(row["y"])
            missing_position = x is None or y is None
            out_of_field = not missing_position and (
                not 0 <= x <= FIELD_LENGTH_YARDS
                or not 0 <= y <= FIELD_WIDTH_YARDS
            )
            if missing_position or out_of_field:
                if position_policy == "strict":
                    raise ValueError("Out-of-bounds or missing tracking position.")
                omitted_frame_ids.add(frame_id)
                if missing_position:
                    omitted_missing_positions += 1
                else:
                    omitted_off_field_positions += 1
                continue

            team = (row.get("team") or "").strip().lower()
            if team not in {"home", "away", "football", "ball", ""}:
                raise ValueError("Invalid home/away team label.")
            if not ident and team not in {"football", "ball", ""}:
                raise ValueError("Ball row must not carry a player-team label.")
            if ident and team not in {"home", "away"}:
                raise ValueError("Player must identify home or away team.")
            side = (
                ("offense" if team == offense_side else "defense")
                if ident and offense_side is not None else None
            )
            entity = {
                "nfl_id": ident or None,
                "is_ball": not ident,
                "team": team or None,
                "side": side,
                "name": (row.get("displayName") or "").strip() or None,
                "jersey": (row.get("jerseyNumber") or "").strip() or None,
                "x": x,
                "y": y,
                "z": None,
                "speed_yards_per_s": _maybe_number(row.get("s")),
                "acceleration_yards_per_s2": _maybe_number(row.get("a")),
                "orientation_deg": _maybe_number(row.get("o")),
                "movement_dir_deg": _maybe_number(row.get("dir")),
                "observed": True,
            }
            frame_entities[frame_id].append(entity)

    if not frame_entities:
        raise ValueError("No tracking rows matched game_id/play_id.")
    indexes = sorted(frame_entities)
    expected = indexes[-1] - indexes[0] + 1
    frames = [
        {
            "frame_id": index,
            "t_seconds_nominal": (index - indexes[0]) / 10.0,
            "players": [e for e in frame_entities[index] if not e["is_ball"]],
            "ball": next((e for e in frame_entities[index] if e["is_ball"]), None),
            "events": sorted(frame_events.get(index, set())),
        }
        for index in indexes
    ]
    return {
        "schema_version": 1,
        "data_mode": "HISTORICAL_RESEARCH",
        "tracking_fidelity": "RECORDED_FRAMES",
        "source": SOURCE,
        "source_license_identifier": license_identifier,
        "rights_attested_by_caller": True,
        "commercial_reuse_authorized": False,
        "model_training_authorized": False,
        "production_model_promoted": False,
        "game_id": game_id,
        "play_id": play_id,
        "possession_team": None,
        "offense_side": offense_side,
        "play_direction": None,
        "coordinate_system": {"x_yards": [0, 120], "y_yards": [0, 53.3], "z_available": False},
        "sample_rate_hz_nominal": 10,
        "frame_count": len(frames),
        "missing_frame_count": expected - len(frames),
        "frame_coverage": len(frames) / expected,
        "rows": matched,
        "position_quality": {
            "policy": position_policy,
            "omitted_missing_position_rows": omitted_missing_positions,
            "omitted_off_field_position_rows": omitted_off_field_positions,
            "omitted_total_position_rows": omitted_missing_positions + omitted_off_field_positions,
            "affected_source_frame_ids": sorted(omitted_frame_ids),
            "never_clamped_or_interpolated": True,
        },
        "source_file_sha256": _file_sha256(path),
        "frames": frames,
    }
