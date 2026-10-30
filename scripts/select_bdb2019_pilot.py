#!/usr/bin/env python3
"""Select a deterministic, diversified 12-play private BDB pilot from metadata ONLY.

The input catalog must already have passed the pinned 2017 NFL tracking source
audit. Selection does not extract player positions, inspect licensed video or
grant new data-use rights. The file is a reproducible pilot plan, not evidence
of successful real-source qualification.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

PLAY_PATTERN = re.compile(r"^[0-9]{1,10}$")
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
PILOT_COUNT = 12
GAME_ID = "2017090700"


def validate_catalog(catalog: object, license_id: str) -> list[dict]:
    if not isinstance(catalog, dict):
        raise ValueError("Pilot catalog must be an object")
    if (
        catalog.get("schema_version") != 1
        or catalog.get("data_mode") != "HISTORICAL_RESEARCH_METADATA_ONLY"
        or catalog.get("qualification_status") != "OFFICIAL_TRACKING_BYTES_AUDITED_VIDEO_PENDING"
        or catalog.get("game_id") != GAME_ID
        or catalog.get("positions_included") is not False
        or catalog.get("source_video_alignment_verified") is not False
        or catalog.get("model_training_authorized") is not False
        or catalog.get("commercial_reuse_authorized") is not False
        or catalog.get("license_declaration") != license_id
        or not isinstance(catalog.get("source_sha256"), str)
        or not SHA256_PATTERN.fullmatch(catalog["source_sha256"])
    ):
        raise ValueError("Pilot requires canonical metadata-only source audit and matching rights declaration")
    plays = catalog.get("plays")
    if not isinstance(plays, list) or len(plays) < PILOT_COUNT:
        raise ValueError("At least 12 recorded official plays required")
    if catalog.get("play_count") != len(plays):
        raise ValueError("Catalog play count mismatch")
    ids: set[str] = set()
    for play in plays:
        if not isinstance(play, dict):
            raise ValueError("Invalid play catalog record")
        pid = play.get("play_id")
        if not isinstance(pid, str) or not PLAY_PATTERN.fullmatch(pid) or pid in ids:
            raise ValueError("Invalid or duplicate play ID")
        ids.add(pid)
        if play.get("game_id") != GAME_ID:
            raise ValueError("Inconsistent game identity")
        for key in ("recorded_frames", "missing_frame_ids", "source_rows",
                    "unrenderable_position_rows", "ball_recorded_frames",
                    "unique_players", "max_players_per_frame"):
            value = play.get(key)
            if type(value) is not int or value < 0:
                raise ValueError("Invalid play metric " + key)
        if play["recorded_frames"] < 1 or play["source_rows"] < 1:
            raise ValueError("Catalog contains empty play")
        if play["ball_recorded_frames"] > play["recorded_frames"]:
            raise ValueError("Ball frame count exceeds recorded frame count")
        ratio = play.get("coverage_ratio")
        if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not (0 < ratio <= 1):
            raise ValueError("Invalid recorded frame coverage")
        if not isinstance(play.get("source_events"), dict):
            raise ValueError("Missing source event inventory")
    return plays


def select_pilot(catalog: object, license_id: str, count: int = PILOT_COUNT) -> dict:
    """Deterministic cross-case technical sample, NOT a representative NFL sample."""
    if count != PILOT_COUNT:
        raise ValueError("The pinned pilot qualification contract requires exactly 12 plays")
    records = validate_catalog(catalog, license_id)
    ordered = sorted(records, key=lambda p: int(p["play_id"]))
    by_id = {p["play_id"]: p for p in ordered}
    chosen: list[dict] = []
    reason: dict[str, list[str]] = {}

    def add(play: dict, why: str) -> None:
        pid = play["play_id"]
        if pid in reason:
            reason[pid].append(why)
        elif len(chosen) < count:
            chosen.append(play)
            reason[pid] = [why]

    for pid in ("938", "2756"):
        if pid not in by_id:
            raise ValueError("Pinned tutorial reference play absent from catalog: " + pid)
        add(by_id[pid], "documented_tutorial_reference")
    selectors = (
        ("largest_frame_span", lambda p: -(p["recorded_frames"] + p["missing_frame_ids"])),
        ("shortest_frame_span", lambda p: p["recorded_frames"] + p["missing_frame_ids"]),
        ("most_missing_frames", lambda p: -p["missing_frame_ids"]),
        ("most_excluded_position_rows", lambda p: -p["unrenderable_position_rows"]),
        ("lowest_frame_coverage", lambda p: p["coverage_ratio"]),
        ("highest_frame_coverage", lambda p: -p["coverage_ratio"]),
        ("fewest_ball_frames", lambda p: p["ball_recorded_frames"]),
        ("most_observed_players", lambda p: -p["unique_players"]),
        ("most_source_event_types", lambda p: -len(p["source_events"])),
        ("highest_source_row_count", lambda p: -p["source_rows"]),
    )
    for label, key in selectors:
        ordered_for_criterion = sorted(ordered, key=lambda p: (key(p), int(p["play_id"])))
        candidate = next((p for p in ordered_for_criterion if p["play_id"] not in reason), None)
        if candidate is not None:
            add(candidate, label)
    # If a future catalog is smaller or criteria overlap, fill the final slots
    # from separated play-ID quantiles so the pilot never depends on row order.
    if len(chosen) < count:
        for i in range(count * 4):
            candidate = ordered[round(i * (len(ordered) - 1) / max(1, count * 4 - 1))]
            if candidate["play_id"] not in reason:
                add(candidate, "coverage_fill")
            if len(chosen) == count:
                break
    if len(chosen) != count:
        raise ValueError("Unable to construct a 12-play technical pilot")
    # File order is stable and matches exporter ordering exactly.
    return {
        "schema_version": 1,
        "data_mode": "BDB2019_PRIVATE_TECHNICAL_PILOT_SELECTION",
        "qualification": "PLAN_ONLY_NOT_EXECUTED",
        "game_id": GAME_ID,
        "source_file_sha256": catalog["source_sha256"],
        "license_declaration": license_id,
        "play_count": count,
        "selected_play_ids": [p["play_id"] for p in chosen],
        "selection_reason_by_play": reason,
        "source_video_alignment_verified": False,
        "model_training_authorized": False,
        "commercial_reuse_authorized": False,
        "note": "Coverage-oriented deterministic smoke sample, not a representative football population",
    }


def validate_selection(selection: object, *, license_id: str, source_sha256: str) -> list[str]:
    """Check selection provenance before exporting original tracking rows."""
    if not isinstance(selection, dict) or (
        selection.get("schema_version") != 1
        or selection.get("data_mode") != "BDB2019_PRIVATE_TECHNICAL_PILOT_SELECTION"
        or selection.get("qualification") != "PLAN_ONLY_NOT_EXECUTED"
        or selection.get("game_id") != GAME_ID
        or selection.get("source_file_sha256") != source_sha256
        or selection.get("license_declaration") != license_id
        or selection.get("play_count") != PILOT_COUNT
        or selection.get("source_video_alignment_verified") is not False
        or selection.get("model_training_authorized") is not False
        or selection.get("commercial_reuse_authorized") is not False
    ):
        raise ValueError("Pilot selection does not match exact original source/rights")
    ids = selection.get("selected_play_ids")
    if (
        not isinstance(ids, list) or len(ids) != PILOT_COUNT
        or any(not isinstance(p, str) or not PLAY_PATTERN.fullmatch(p) for p in ids)
        or len(set(ids)) != PILOT_COUNT
    ):
        raise ValueError("Selection must contain 12 distinct numeric play IDs")
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--license-id", required=True)
    parser.add_argument("--acknowledge-source-terms", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_source_terms or not args.license_id.strip():
        parser.error("Review applicable rights, then explicitly acknowledge source terms")
    if not args.catalog.is_file() or args.catalog.is_symlink() or args.catalog.stat().st_size > 1_000_000:
        parser.error("Catalog must be a regular, bounded local JSON file")
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    selection = select_pilot(catalog, args.license_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_WRONLY | os.O_EXCL | os.O_CREAT, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(selection, out, sort_keys=True, indent=2)
        out.write("\n")
    print(f"Created private position-free plan for {PILOT_COUNT} source-observed plays.")
    print("Not a source-data execution, representative sample, rights grant or film qualification.")


if __name__ == "__main__":
    main()
