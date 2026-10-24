"""One-pass, fully local NFL BDB 2019 multi-play replay exporter.

The tracking CSV is authenticated once. Selected plays are partitioned in one
stream, independently parsed with the existing audited replay adapter, and
committed as one new directory only after all plays pass qualification.
No raw tracking or normalized coordinates are sent to any service.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from player_state_engine.product.bdb2019_source_qualification import (
    GAME_REQUIRED,
    KNOWN_TRACKING_PLAY_PROFILES,
    PLAY_REQUIRED,
    SOURCE_FILES,
    SOURCE_GAME_ID,
    _unique_metadata_row,
    verify_file_identities,
)
from player_state_engine.product.gameday_legacy_tracking import import_bdb_2019_example
from player_state_engine.product.gameday_tracking import write_replay_json

MAX_PLAYS = 12
MAX_TRACKING_ROWS = 400_000
MAX_ROWS_PER_PLAY = 25_000


def validate_play_ids(play_ids: list[str] | tuple[str, ...]) -> list[str]:
    if not 1 <= len(play_ids) <= MAX_PLAYS:
        raise ValueError(f"Select 1 to {MAX_PLAYS} play IDs for one research session.")
    if any(not isinstance(p, str) or not p.isascii() or not p.isdecimal()
           or not 1 <= len(p) <= 10 for p in play_ids):
        raise ValueError("Play IDs must be ASCII decimal strings (1 to 10 digits).")
    if len(set(play_ids)) != len(play_ids):
        raise ValueError("Duplicate requested play ID.")
    return list(play_ids)


def _positive(value: str | None, label: str, *, optional: bool = False) -> int | None:
    if value is None or value.strip().lower() in {"", "na", "n/a", "null", "none"}:
        if optional:
            return None
        raise ValueError("Missing source " + label)
    try:
        number = int(value)
    except ValueError as exc:
        raise ValueError("Invalid source " + label) from exc
    if number < 0 or (label in {"season", "week", "quarter"} and number == 0):
        raise ValueError("Out-of-range source " + label)
    if label == "down" and number > 4:
        raise ValueError("Invalid source down.")
    return number


def _metadata(
    root: Path,
    play_ids: list[str],
    expectations: dict[str, tuple[str, str, int]],
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    game = _unique_metadata_row(
        root / expectations["games"][0], columns=GAME_REQUIRED,
        target={"gameId": SOURCE_GAME_ID},
    )
    home = (game.get("homeTeamAbbr") or "").strip()
    away = (game.get("visitorTeamAbbr") or "").strip()
    if not home or not away or home == away:
        raise ValueError("Invalid official game home/visitor identities.")
    output: dict[str, dict[str, str]] = {}
    with (root / expectations["plays"][0]).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if PLAY_REQUIRED - set(reader.fieldnames or []):
            raise ValueError("Official plays.csv missing required metadata columns.")
        for row in reader:
            if row.get("gameId") != SOURCE_GAME_ID or row.get("playId") not in play_ids:
                continue
            pid = row["playId"]
            if pid in output:
                raise ValueError("Duplicate official game/play metadata key.")
            possession = (row.get("possessionTeam") or "").strip()
            if possession not in {home, away}:
                raise ValueError("Possession team cannot be reconciled with verified home/visitor metadata.")
            _positive(row.get("quarter"), "quarter")
            _positive(row.get("down"), "down", optional=True)
            _positive(row.get("yardsToGo"), "yards to go", optional=True)
            output[pid] = row
    if set(output) != set(play_ids):
        raise ValueError("One or more requested plays are missing verified NFL metadata.")
    return game, output


def _nullable_label(value: str | None) -> str | None:
    if value is None or value.strip().lower() in {"", "na", "n/a", "null", "none"}:
        return None
    return value.strip()


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def export_bdb2019_replay_batch(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    play_ids: list[str] | tuple[str, ...],
    license_acknowledged: bool = False,
    license_identifier: str = "",
    expectations: dict[str, tuple[str, str, int]] | None = None,
) -> dict[str, Any]:
    """Export selected recorded plays atomically as a new private directory.

    Custom expectations exist only for synthetic tests: no noncanonical source
    can receive official-qualification status.
    """
    selected = validate_play_ids(play_ids)
    if not license_acknowledged or not license_identifier.strip():
        raise ValueError("Review source rights and explicitly supply a source terms declaration.")
    expected = SOURCE_FILES if expectations is None else expectations
    root = Path(source_dir).resolve()
    out = Path(output_dir).resolve()
    if root == out or out.exists():
        raise ValueError("Choose a new output directory separate from the source CSVs.")
    if not set(("tracking", "plays", "games")) == set(expected):
        raise ValueError("All three tracking, plays and games identities are required.")
    identities = verify_file_identities(root, expectations=expected)
    canonical = expected == SOURCE_FILES
    game, rows_by_play = _metadata(root, selected, expected)
    home, away = game["homeTeamAbbr"].strip(), game["visitorTeamAbbr"].strip()
    season = _positive(game["season"], "season")
    week = _positive(game["week"], "week")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pse-playlab-staging-", dir=out.parent) as temporary:
        stage = Path(temporary)
        csv_paths = {pid: stage / f".source-{pid}.csv" for pid in selected}
        handles: dict[str, Any] = {}
        writers: dict[str, csv.DictWriter] = {}
        counts = dict.fromkeys(selected, 0)
        try:
            with (root / expected["tracking"][0]).open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                fields = list(reader.fieldnames or [])
                if not {"gameId", "playId", "nflId", "frame.id", "team", "x", "y"}.issubset(fields):
                    raise ValueError("Tracking CSV is missing required source fields.")
                for pid in selected:
                    handles[pid] = csv_paths[pid].open("x", encoding="utf-8", newline="")
                    writers[pid] = csv.DictWriter(handles[pid], fieldnames=fields)
                    writers[pid].writeheader()
                total = 0
                for row in reader:
                    total += 1
                    if total > MAX_TRACKING_ROWS:
                        raise ValueError("Tracking source exceeded safety row cap.")
                    if row["gameId"] != SOURCE_GAME_ID:
                        raise ValueError("Pinned historical tracking contained another game.")
                    pid = row["playId"]
                    if pid in writers:
                        counts[pid] += 1
                        if counts[pid] > MAX_ROWS_PER_PLAY:
                            raise ValueError("Requested play exceeded safe row limit.")
                        writers[pid].writerow(row)
        finally:
            for handle in handles.values():
                handle.close()
        if any(not counts[pid] for pid in selected):
            raise ValueError("Requested play is absent from pinned tracking CSV.")

        exported: list[dict[str, Any]] = []
        for pid in selected:
            row = rows_by_play[pid]
            possession = row["possessionTeam"].strip()
            side = "home" if possession == home else "away"
            replay = import_bdb_2019_example(
                csv_paths[pid], game_id=SOURCE_GAME_ID, play_id=pid,
                license_acknowledged=True, license_identifier=license_identifier,
                offense_side=side, position_policy="omit_off_field_with_audit",
            )
            if replay["rows"] != counts[pid]:
                raise ValueError("Source extraction and replay record counts disagree.")
            # Replays came exclusively from the hash-verified complete CSV, not
            # from an independent unrelated filtered-CSV publication.
            replay["source_file_sha256"] = identities["tracking"]["sha256"]
            replay["possession_team"] = possession
            replay["source_play_metadata"] = {
                "provenance": (
                    "PINNED_OFFICIAL_PLAYS_AND_GAMES_CSV"
                    if canonical else "NONCANONICAL_TEST_FIXTURE"
                ),
                "season": season, "week": week,
                "home_team": home, "visitor_team": away,
                "possession_team": possession, "offense_side": side,
                "quarter": _positive(row.get("quarter"), "quarter"),
                "down": _positive(row.get("down"), "down", optional=True),
                "yards_to_go": _positive(row.get("yardsToGo"), "yards to go", optional=True),
                "offense_formation_charted": _nullable_label(row.get("offenseFormation")),
                "offense_personnel_charted": _nullable_label(row.get("personnel.offense")),
            }
            if canonical and pid in KNOWN_TRACKING_PLAY_PROFILES:
                profile = KNOWN_TRACKING_PLAY_PROFILES[pid]
                quality = replay["position_quality"]
                snap_ids = [
                    frame["frame_id"] for frame in replay["frames"]
                    if any(e.lower() in {"ball_snap", "snap", "snap_direct"} for e in frame["events"])
                ]
                actual = {
                    "rows": replay["rows"], "frames": replay["frame_count"],
                    "ball_frames": sum(f["ball"] is not None for f in replay["frames"]),
                    "omitted_missing": quality["omitted_missing_position_rows"],
                    "omitted_outside": quality["omitted_off_field_position_rows"],
                    "snap_frame": snap_ids[0] if len(snap_ids) == 1 else None,
                    "observed_player_ids": len({
                        p["nfl_id"] for f in replay["frames"] for p in f["players"]
                    }),
                }
                if actual != profile:
                    raise ValueError("Known original NFL play audit fingerprint disagrees.")
            if not replay["frames"]:
                raise ValueError("No recorded frames for play " + pid)
            if not any(p["side"] == "offense" for f in replay["frames"] for p in f["players"]):
                raise ValueError("Missing source-observed offensive players.")
            if not any(p["side"] == "defense" for f in replay["frames"] for p in f["players"]):
                raise ValueError("Missing source-observed defensive players.")
            filename = f"{SOURCE_GAME_ID}-{pid}-research-replay.json"
            dest = write_replay_json(replay, stage / filename)
            exported.append({
                "play_id": pid, "file": filename, "sha256": _file_sha256(dest),
                "source_rows": counts[pid],
                "recorded_frames": replay["frame_count"],
                "missing_source_frames": replay["missing_frame_count"],
                "omitted_position_rows": replay["position_quality"]["omitted_total_position_rows"],
                "possession_team": possession,
                "metadata_provenance": replay["source_play_metadata"]["provenance"],
            })
            csv_paths[pid].unlink()
        # Fail closed on source edits occurring during the extraction or
        # conversion. Never assign a previously verified hash to drifted CSVs.
        if verify_file_identities(root, expectations=expected) != identities:
            raise ValueError("Pinned source changed during the research replay export.")
        manifest = {
            "schema_version": 1, "data_mode": "HISTORICAL_RESEARCH_BATCH_MANIFEST",
            "qualification_status": (
                "PINNED_SOURCE_AND_PLAY_METADATA_VIDEO_PENDING" if canonical
                else "NONCANONICAL_FIXTURE_ONLY"
            ),
            "game_id": SOURCE_GAME_ID,
            "source_file_sha256": identities["tracking"]["sha256"],
            "source_identities": identities,
            "source_video_alignment_verified": False,
            "model_training_authorized": False,
            "commercial_reuse_authorized": False,
            "license_declaration": license_identifier,
            "play_count": len(exported), "plays": exported,
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        if out.exists():
            raise ValueError("Output directory was created while the batch was processing.")
        os.rename(stage, out)
    return manifest
