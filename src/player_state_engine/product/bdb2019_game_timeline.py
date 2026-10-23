"""Source-verified, position-free 2017 NFL game timeline for Fourth Down Lab.

A timeline is a join of pinned plays/games metadata with the existing local
recorded-play catalog. It NEVER infers drives or exports tracking coordinates.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Mapping

from player_state_engine.product.bdb2019_source_qualification import (
    GAME_REQUIRED,
    PLAY_REQUIRED,
    SOURCE_FILES,
    SOURCE_GAME_ID,
    verify_file_identities,
)

CLOCK = re.compile(r"^(?:[0-9]|[0-5][0-9]):[0-5][0-9]$")
DESCRIPTION_LIMIT = 500
CATALOG_LIMIT = 2_000_000


def _read_rows(path: Path, columns: set[str], *, limit: int) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not columns <= set(reader.fieldnames or []):
            raise ValueError(f"Source {path.name} lacks required metadata columns.")
        rows = []
        for row in reader:
            if len(rows) >= limit:
                raise ValueError(f"Metadata source {path.name} exceeded row cap.")
            rows.append(row)
    return rows


def _integer(raw: str | None, field: str, *, low: int, high: int) -> int:
    try:
        value = int(raw) if raw is not None else None
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {field} in source metadata") from exc
    if value is None or value < low or value > high:
        raise ValueError(f"Invalid {field} in source metadata")
    return value


def _optional_text(raw: str | None, limit: int = DESCRIPTION_LIMIT) -> str | None:
    value = (raw or "").strip()
    if not value or value.lower() in {"nan", "na", "null", "none"}:
        return None
    if len(value) > limit or any(ord(c) < 32 and c not in "\t" for c in value):
        raise ValueError("Metadata text exceeds bounds or contains control characters")
    return value


def build_bdb2019_game_timeline(
    source_dir: str | Path,
    play_catalog_json: str | Path,
    *,
    license_acknowledged: bool = False,
    license_identifier: str = "",
    expectations: Mapping[str, tuple[str, str, int]] = SOURCE_FILES,
) -> dict[str, Any]:
    """Require exact source bytes; fixture identities never grant official status."""
    if not license_acknowledged or not license_identifier.strip():
        raise ValueError("Source terms acknowledgement and identifier are required.")
    source = Path(source_dir)
    identities = verify_file_identities(source, expectations=expectations)
    catalog_path = Path(play_catalog_json)
    if catalog_path.stat().st_size > CATALOG_LIMIT:
        raise ValueError("Play catalog exceeds 2 MB.")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if (
        not isinstance(catalog, dict)
        or catalog.get("data_mode") != "HISTORICAL_RESEARCH_METADATA_ONLY"
        or catalog.get("positions_included") is not False
        or catalog.get("source_video_alignment_verified") is not False
        or catalog.get("game_id") != SOURCE_GAME_ID
        or catalog.get("source_sha256") != identities["tracking"]["sha256"]
        or not isinstance(catalog.get("plays"), list)
        or not catalog["plays"]
        or catalog.get("play_count") != len(catalog["plays"])
        or len(catalog["plays"]) > 1000
    ):
        raise ValueError("Position-free catalog provenance or shape disagrees with source.")
    ids = set()
    for play in catalog["plays"]:
        if not isinstance(play, dict) or set(play).intersection({"frames", "players", "x", "y", "tracking"}):
            raise ValueError("Catalog cannot include tracking positions or frames.")
        pid = play.get("play_id")
        if (
            not isinstance(pid, str) or not pid.isdecimal()
            or play.get("game_id") != SOURCE_GAME_ID or pid in ids
        ):
            raise ValueError("Duplicate or invalid catalog play identity.")
        ids.add(pid)

    games = _read_rows(source / expectations["games"][0], GAME_REQUIRED, limit=2000)
    matches = [g for g in games if g["gameId"] == SOURCE_GAME_ID]
    if len(matches) != 1:
        raise ValueError("Official game metadata must have one matching game.")
    game = matches[0]
    home, away = game["homeTeamAbbr"].strip(), game["visitorTeamAbbr"].strip()
    if not home or not away or home == away:
        raise ValueError("Invalid recorded game home/away identities.")

    metadata = _read_rows(source / expectations["plays"][0], PLAY_REQUIRED, limit=20000)
    by_id: dict[str, dict[str, str]] = {}
    for row in metadata:
        if row["gameId"] != SOURCE_GAME_ID or row["playId"] not in ids:
            continue
        pid = row["playId"]
        if pid in by_id:
            raise ValueError(f"Duplicate official play metadata for {pid}.")
        by_id[pid] = row
    if set(by_id) != ids:
        raise ValueError("Tracking play catalog has unmatched official play identities.")

    entries = []
    for pid in sorted(ids, key=int):
        row = by_id[pid]
        possession = row["possessionTeam"].strip()
        if possession not in {home, away}:
            raise ValueError(f"Unverified possession side on play {pid}.")
        clock = _optional_text(row.get("GameClock"), 12)
        if clock and not CLOCK.fullmatch(clock):
            raise ValueError(f"Malformed official game clock on play {pid}.")
        # This side/number represents charted line of scrimmage, not coordinates.\n        line_side = _optional_text(row.get("yardlineSide"), 8)\n        line_number = row.get("yardlineNumber")\n        if bool(line_side) != bool(line_number and line_number.strip()):\n            raise ValueError(f"Incomplete charted yardline on play {pid}.")\n        if line_side and line_side not in {home, away}:\n            raise ValueError(f"Invalid charted yardline side on play {pid}.")\n        yardline = _integer(line_number, "yardlineNumber", low=0, high=50) if line_side else None\n        # playId is a documented source identifier, NOT an inferred drive boundary.
        entries.append({
            "game_id": SOURCE_GAME_ID,
            "play_id": pid,
            "quarter": _integer(row.get("quarter"), "quarter", low=1, high=5),
            "down": _integer(row.get("down"), "down", low=0, high=4),
            "yards_to_go": _integer(row.get("yardsToGo"), "yardsToGo", low=0, high=100),
            "possession_team": possession,
            "offense_side": "home" if possession == home else "away",
            "game_clock_charted": clock,\n            "yardline_side_charted": line_side,\n            "yardline_number_charted": yardline,
            "description_charted": _optional_text(row.get("playDescription")),
            "formation_charted": _optional_text(row.get("offenseFormation"), 120),
            "personnel_charted": _optional_text(row.get("personnel.offense"), 120),
            "source_tracking_rows": next(p["source_rows"] for p in catalog["plays"] if p["play_id"] == pid),
        })
    canonical = dict(expectations) == SOURCE_FILES
    return {
        "schema_version": 1,
        "data_mode": "HISTORICAL_RESEARCH_GAME_TIMELINE",
        "qualification_status": (
            "SOURCE_AND_STRUCTURE_QUALIFIED_VIDEO_PENDING"
            if canonical else "SYNTHETIC_OR_NONCANONICAL_FIXTURE_ONLY"
        ),
        "game_id": SOURCE_GAME_ID,
        "season": _integer(game.get("season"), "season", low=2000, high=2100),
        "week": _integer(game.get("week"), "week", low=1, high=22),
        "home_team": home,
        "away_team": away,
        "tracking_source_sha256": identities["tracking"]["sha256"],
        "plays_source_sha256": identities["plays"]["sha256"],
        "games_source_sha256": identities["games"]["sha256"],
        "source_commit": "9ad0b4b2ea36697e29e44e2399512cc1ce70358c" if canonical else None,
        "play_count": len(entries),
        "positions_included": False,
        "drive_boundaries_verified": False,
        "source_video_alignment_verified": False,
        "commercial_reuse_authorized": False,
        "model_training_authorized": False,
        "plays": entries,
    }


def write_game_timeline(payload: dict[str, Any], output: str | Path) -> Path:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return target
