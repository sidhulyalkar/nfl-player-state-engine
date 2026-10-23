"""Qualify a *local* copy of the NFL's public 2019 BDB research example.

This qualification checks source file bytes and structural playback integrity.
It does NOT independently approve redistribution, model training or commercial
use, and does not validate tracking positions against broadcast/All-22 film.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from player_state_engine.product.gameday_legacy_tracking import import_bdb_2019_example

SOURCE_REPOSITORY = "nfl-football-ops/Big-Data-Bowl"
SOURCE_COMMIT = "9ad0b4b2ea36697e29e44e2399512cc1ce70358c"
SOURCE_GAME_ID = "2017090700"
SOURCE_FILES: dict[str, tuple[str, str, int]] = {
    "tracking": (
        "tracking_gameId_2017090700.csv",
        "2394ce60e8947eb7e73d36515c021a0699768ca1",
        31659157,
    ),
    "plays": ("plays.csv", "08b1ad5f88efb89939c17a8793a55fcddf2511ca", 3038568),
    "games": ("games.csv", "3835c453e8c37342394267c384948b7d88fe55f1", 15825),
}
PLAY_REQUIRED = {"gameId", "playId", "possessionTeam", "quarter", "down", "yardsToGo"}
GAME_REQUIRED = {"gameId", "homeTeamAbbr", "visitorTeamAbbr", "season", "week"}


def file_identifiers(path: Path) -> dict[str, Any]:
    """Stream SHA-256 and canonical Git SHA-1 (including blob header)."""
    size = path.stat().st_size
    git = hashlib.sha1()
    git.update(f"blob {size}\0".encode("ascii"))
    sha256 = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            git.update(chunk)
            sha256.update(chunk)
    return {"bytes": size, "git_blob_sha1": git.hexdigest(), "sha256": sha256.hexdigest()}


def verify_file_identities(
    source_dir: str | Path,
    *,
    expectations: Mapping[str, tuple[str, str, int]] = SOURCE_FILES,
) -> dict[str, dict[str, Any]]:
    """Reject changed official bytes BEFORE using the data for qualification."""
    root = Path(source_dir)
    result: dict[str, dict[str, Any]] = {}
    for kind, (name, expected_blob, expected_size) in expectations.items():
        path = root / name
        if not path.is_file():
            raise ValueError(f"Missing {kind} source CSV: {path}")
        actual = file_identifiers(path)
        if actual["bytes"] != expected_size or actual["git_blob_sha1"] != expected_blob:
            raise ValueError(
                f"{kind} source bytes do not match pinned official Git blob. "
                "Review the source revision and update the qualified identity explicitly."
            )
        result[kind] = {"file": name, **actual, "identity_match": True}
    if set(result) != {"tracking", "plays", "games"}:
        raise ValueError("Exactly tracking, plays and games source contracts are required.")
    return result


def _unique_metadata_row(
    path: Path,
    *,
    columns: set[str],
    target: dict[str, str],
) -> dict[str, str]:
    found: dict[str, str] | None = None
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = columns - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Missing metadata columns in {path.name}: {sorted(missing)}")
        for row in reader:
            if all(row.get(key) == value for key, value in target.items()):
                if found is not None:
                    raise ValueError(f"Duplicate metadata key in {path.name}: {target}")
                found = row
    if found is None:
        raise ValueError(f"Requested game/play metadata is absent in {path.name}: {target}")
    return found


def _integer(value: str | None, description: str, minimum: int = 0) -> int:
    try:
        n = int(value) if value is not None else None
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {description} in official metadata") from exc
    if n is None or n < minimum:
        raise ValueError(f"Invalid {description} in official metadata")
    return n


def qualify_bdb2019_play(
    source_dir: str | Path,
    *,
    game_id: str = SOURCE_GAME_ID,
    play_id: str = "938",
    license_acknowledged: bool = False,
    license_identifier: str = "",
    expectations: Mapping[str, tuple[str, str, int]] = SOURCE_FILES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (summary qualification report, normalized recorded replay).

    For tests, expectations can specify *fixture* blob hashes. Such tests are
    explicitly flagged noncanonical; they cannot qualify NFL source bytes.
    """
    if not license_acknowledged or not license_identifier.strip():
        raise ValueError("Explicit source terms acknowledgement and declaration are required.")
    if game_id != SOURCE_GAME_ID:
        raise ValueError("Only the pinned official 2017 game is qualified by this contract.")
    source_root = Path(source_dir)
    identities = verify_file_identities(source_root, expectations=expectations)
    game = _unique_metadata_row(
        source_root / expectations["games"][0],
        columns=GAME_REQUIRED,
        target={"gameId": game_id},
    )
    play = _unique_metadata_row(
        source_root / expectations["plays"][0],
        columns=PLAY_REQUIRED,
        target={"gameId": game_id, "playId": play_id},
    )
    home, away = game["homeTeamAbbr"].strip(), game["visitorTeamAbbr"].strip()
    possession = play["possessionTeam"].strip()
    if not home or not away or home == away or possession not in {home, away}:
        raise ValueError("Possession team cannot be reconciled with verified home/visitor metadata.")
    offense_side = "home" if possession == home else "away"
    season = _integer(game["season"], "season", minimum=2000)
    week = _integer(game["week"], "week", minimum=1)
    quarter = _integer(play["quarter"], "quarter", minimum=1)
    down = _integer(play["down"], "down")
    yards_to_go = _integer(play["yardsToGo"], "yardsToGo")
    replay = import_bdb_2019_example(
        source_root / expectations["tracking"][0],
        game_id=game_id,
        play_id=play_id,
        license_acknowledged=license_acknowledged,
        license_identifier=license_identifier,
        offense_side=offense_side,
    )
    if replay["source_file_sha256"] != identities["tracking"]["sha256"]:
        raise ValueError("Tracking CSV mutated after source identity check.")
    if not replay["frames"]:
        raise ValueError("Source tracking yielded no frames.")
    observed_side: set[str] = set()
    counts: list[int] = []
    observed_player_ids: set[str] = set()
    observed_balls = 0
    snap_ids: list[int] = []
    for frame in replay["frames"]:
        counts.append(len(frame["players"]))
        observed_balls += int(frame["ball"] is not None)
        if any(label.lower() in {"ball_snap", "snap", "snap_direct"} for label in frame["events"]):
            snap_ids.append(frame["frame_id"])
        if len(frame["players"]) > 22:
            raise ValueError("More than 22 player identities in a source frame.")
        for player in frame["players"]:
            side = "home" if player["team"] == "home" else "away"
            expected = "offense" if side == offense_side else "defense"
            if player["side"] != expected:
                raise ValueError("A player's team and source-derived offense/defense side disagree.")
            observed_player_ids.add(player["nfl_id"])
            observed_side.add(player["side"])
    if not {"offense", "defense"}.issubset(observed_side):
        raise ValueError("Both offense and defense must have observed tracked players.")
    warnings: list[str] = []
    if not snap_ids:
        warnings.append("No source-labeled snap frame; pre-snap comparison remains unavailable.")
    if observed_balls < replay["frame_count"]:
        warnings.append("Ball is missing from some source frames; no ball positions will be inferred.")
    if min(counts) < 22:
        warnings.append("Some recorded frames have fewer than 22 tracked players.")
    canonical = dict(expectations) == SOURCE_FILES
    first, last = replay["frames"][0], replay["frames"][-1]
    report: dict[str, Any] = {
        "schema_version": 1,
        "qualification_status": (
            "SOURCE_AND_STRUCTURE_QUALIFIED_VIDEO_PENDING"
            if canonical else "SYNTHETIC_OR_NONCANONICAL_FIXTURE_ONLY"
        ),
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": SOURCE_COMMIT if canonical else "noncanonical-local-test-fixture",
        "source_identities": identities,
        "license_declaration": license_identifier,
        "rights_attested_by_caller": True,
        "commercial_reuse_authorized": False,
        "model_training_authorized": False,
        "source_video_alignment_verified": False,
        "game": {
            "game_id": game_id,
            "season": season,
            "week": week,
            "home_team": home,
            "away_team": away,
        },
        "play": {
            "play_id": play_id,
            "quarter": quarter,
            "down": down,
            "yards_to_go": yards_to_go,
            "possession_team": possession,
            "offense_side_verified_from_metadata": offense_side,
            "offense_formation_charted": play.get("offenseFormation") or None,
            "offense_personnel_charted": play.get("personnel.offense") or None,
        },
        "tracking": {
            "frame_count": replay["frame_count"],
            "source_rows": replay["rows"],
            "first_frame_id": first["frame_id"],
            "last_frame_id": last["frame_id"],
            "missing_frame_count": replay["missing_frame_count"],
            "frame_coverage": replay["frame_coverage"],
            "duration_seconds_nominal": last["t_seconds_nominal"],
            "unique_player_ids": len(observed_player_ids),
            "players_per_frame_min": min(counts),
            "players_per_frame_max": max(counts),
            "ball_observed_frames": observed_balls,
            "source_labeled_snap_frames": snap_ids,
        },
        "warnings": warnings,
    }
    return report, replay


def write_qualification_report(report: Mapping[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return path
