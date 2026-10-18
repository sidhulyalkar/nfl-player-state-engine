"""Source-aware, public nflverse Sunday scoreboard.

The nflverse schedule release can update every ~5 minutes but is NOT an
authoritative, seconds-level play-by-play or in-progress score service.
No NFL.com scraping, ESPN private APIs, paid tracking, or inferred plays.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SCHEDULE_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
)
SOURCE_LABEL = "nflverse schedules/games.csv (Lee Sharpe / nflverse)"
SOURCE_LICENSE_NOTE = (
    "nflverse-data repository publishes CC BY 4.0; upstream nfldata and "
    "downstream commercial rights should be checked separately."
)
MIN_REFRESH_SECONDS = 300
MAX_DOWNLOAD_BYTES = 12_000_000
_LOCK = threading.Lock()
_REQUIRED = {"game_id", "season", "game_type", "week", "gameday", "gametime",
             "away_team", "home_team", "away_score", "home_score"}


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _read_csv(data: bytes) -> list[dict[str, str]]:
    if not data or len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Empty or oversized schedule download.")
    decoded = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(decoded))
    if not _REQUIRED.issubset(set(reader.fieldnames or [])):
        raise ValueError("Public schedule release schema is missing required fields.")
    rows = list(reader)
    if not 50 <= len(rows) <= 50000:
        raise ValueError("Schedule row count is implausible.")
    return rows


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        name = Path(stream.name)
        stream.write(payload)
    try:
        name.replace(path)
    finally:
        name.unlink(missing_ok=True)


def _download_public_schedule() -> bytes:
    request = Request(SCHEDULE_URL, headers={
        "User-Agent": "FourthDownLab/0.1 (public nflverse release; 5min max polling)",
        "Accept": "text/csv",
    })
    with urlopen(request, timeout=14) as response:  # noqa: S310 - fixed, allowlisted URL
        payload = response.read(MAX_DOWNLOAD_BYTES + 1)
    _read_csv(payload)
    return payload


def refresh_schedule(
    root: str | Path,
    *,
    now: datetime | None = None,
    fetcher=None,
) -> dict[str, object]:
    """Throttle across processes using cache metadata, and retain last good file.

    A process-level lock serializes refreshes within a worker. Multiworker
    deployments should use a single scheduled refresher instead.
    """
    current = now or datetime.now(UTC)
    base = Path(root)
    csv_path = base / "games.csv"
    meta_path = base / "source.json"
    with _LOCK:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            meta = {}
        last = _timestamp(meta.get("fetched_at_utc"))
        if csv_path.exists() and last and (current - last).total_seconds() < MIN_REFRESH_SECONDS:
            return {"refreshed": False, "throttled": True, "error": None}
        try:
            payload = (fetcher or _download_public_schedule)()
            _read_csv(payload)
            _write_atomic(csv_path, payload)
            _write_atomic(meta_path, json.dumps({
                "source": SOURCE_LABEL,
                "url": SCHEDULE_URL,
                "fetched_at_utc": _iso(current),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }).encode("utf-8"))
            return {"refreshed": True, "throttled": False, "error": None}
        except (OSError, ValueError, UnicodeError) as exc:
            return {"refreshed": False, "throttled": False, "error": str(exc)}


def _score(value: str | None) -> int | None:
    if value is None or str(value).strip() in {"", "NA", "NaN"}:
        return None
    try:
        n = int(float(value))
    except (ValueError, TypeError):
        return None
    return n if 0 <= n < 200 else None


def _kickoff(row: dict[str, str]) -> datetime | None:
    try:
        dt = datetime.strptime(
            row["gameday"] + " " + (row.get("gametime") or "00:00"), "%Y-%m-%d %H:%M"
        )
        return dt.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
    except (ValueError, KeyError):
        return None


def normalize_schedule(
    rows: list[dict[str, str]],
    *,
    season: int,
    week: int | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    current = now or datetime.now(UTC)
    filtered: list[tuple[dict[str, str], datetime | None]] = []
    for r in rows:
        try:
            if int(r["season"]) != season or r["game_type"] != "REG":
                continue
            if not 1 <= int(r["week"]) <= 18:
                continue
        except (KeyError, ValueError):
            continue
        filtered.append((r, _kickoff(r)))

    if week is None and filtered:
        # Find the closest game to the current timestamp: covers Sun, Mon and Thu.
        closest = min(
            (pair for pair in filtered if pair[1]),
            key=lambda pair: abs((pair[1] - current).total_seconds()),
            default=None,
        )
        week = int(closest[0]["week"]) if closest else 1
    if week is None:
        week = 1
    games = []
    for row, kickoff in filtered:
        if int(row["week"]) != week:
            continue
        away = _score(row.get("away_score"))
        home = _score(row.get("home_score"))
        if away is None or home is None:
            away = home = None
        game_id = str(row["game_id"])
        if not game_id.startswith(str(season) + "_"):
            # Refuse to attribute malformed source game IDs to a 2026 matchup.
            continue
        games.append({
            "game_id": game_id,
            "away_team": row["away_team"],
            "home_team": row["home_team"],
            "away_score": away,
            "home_score": home,
            "kickoff_utc": _iso(kickoff) if kickoff else None,
            "score_state": "PUBLISHED_UNVERIFIED" if home is not None else "NOT_PUBLISHED",
            "play_by_play_available": False,
            "possession": None,
            "down": None,
            "distance": None,
            "quarter": None,
            "clock": None,
            "tracking_available": False,
            "last_play": None,
        })
    games.sort(key=lambda g: (g["kickoff_utc"] or "", g["game_id"]))
    return {"week": week, "games": games}


def build_sunday_board(
    *,
    root: str | Path,
    season: int,
    week: int | None = None,
    refresh: bool = False,
    now: datetime | None = None,
    fetcher=None,
) -> dict[str, object]:
    current = now or datetime.now(UTC)
    base = Path(root)
    refreshed = (
        refresh_schedule(base, now=current, fetcher=fetcher)
        if refresh else {"refreshed": False, "throttled": False, "error": None}
    )
    csv_path = base / "games.csv"
    meta_path = base / "source.json"
    if not csv_path.exists():
        raise FileNotFoundError(
            "No public schedule snapshot available. Set refresh=true to fetch "
            "the published nflverse games release."
        )
    raw = csv_path.read_bytes()
    rows = _read_csv(raw)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        meta = {}
    fetched = _timestamp(meta.get("fetched_at_utc"))
    age = max(0., (current - fetched).total_seconds()) if fetched else None
    checksum = hashlib.sha256(raw).hexdigest()
    integrity = bool(meta.get("sha256") == checksum)
    normalized = normalize_schedule(rows, season=season, week=week, now=current)
    return {
        "schema_version": 1,
        "authority": "PUBLIC_SCHEDULE_NOT_LIVE_PBP",
        "data_mode": "PUBLIC_DELAYED_UNVERIFIED",
        "tracking_fidelity": "NO_TRACKING",
        "season": season,
        **normalized,
        "source": {
            "name": SOURCE_LABEL,
            "url": SCHEDULE_URL,
            "license_note": SOURCE_LICENSE_NOTE,
            "fetched_at_utc": _iso(fetched) if fetched else None,
            "age_seconds": age,
            "stale": age is None or age > 600,
            "integrity_verified": integrity,
            "sha256": checksum,
            "refresh": refreshed,
        },
        "features_available": {
            "published_scores": True,
            "live_pbp": False,
            "player_grades": False,
            "3d_tracking": False,
            "coaching_call_truth": False,
        },
        "served_at_utc": _iso(current),
    }
