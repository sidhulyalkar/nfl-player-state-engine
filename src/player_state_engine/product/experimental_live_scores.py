"""Opt-in, local-only experimental NFL scoreboard evaluation.

ESPN's publicly reachable Site API is undocumented and does NOT grant
commercial, redistribution, or live-data license rights. This is a
read-only, attributed local validation pilot, not an approved provider.
No play-by-play, tracking, player grades, or inferred scoring events.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from typing import Any
from urllib.request import Request, urlopen

ENDPOINT = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
MIN_FETCH_SECONDS = 30
STALE_AFTER_SECONDS = 90
MAX_BYTES = 1_200_000
_LOCK = threading.Lock()
_CACHE: dict[tuple[int, int | None], dict[str, Any]] = {}
_ALIASES = {"WSH": "WAS", "JAX": "JAX", "LAR": "LA", "ARZ": "ARI"}
_ALLOWED = {"pre", "in", "post"}


def _int(value: Any, low: int, high: int) -> int:
    try:
        result = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid source integer") from exc
    if isinstance(value, bool) or not low <= result <= high:
        raise ValueError("Out-of-range source integer")
    return result


def _text(value: Any, limit: int = 90) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        return None
    if any(ord(ch) < 32 for ch in value):
        return None
    return value.strip()


def _utc(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(UTC).isoformat()
    except ValueError:
        return None


def _download(season: int, week: int | None) -> dict[str, Any]:
    query = f"?season={season}&seasontype=2"
    if week is not None:
        query += f"&week={week}"
    request = Request(ENDPOINT + query, headers={
        "Accept": "application/json",
        "User-Agent": "FourthDownLab-LocalScoreEvaluation/0.1",
    })
    with urlopen(request, timeout=12) as response:  # noqa: S310 - fixed HTTPS allowlisted host
        raw = response.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Empty or oversized experimental scoreboard response")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Unexpected experimental scoreboard schema")
    return payload


def normalize_live_scores(payload: dict[str, Any], *, season: int,
                          expected_week: int | None = None) -> dict[str, Any]:
    """Normalize only source-reported data; reject status and identity ambiguity."""
    source_season = payload.get("season")
    if not isinstance(source_season, dict) or _int(source_season.get("year"), 2000, 2100) != season:
        raise ValueError("Source season does not match request")
    week_meta = payload.get("week")
    if not isinstance(week_meta, dict):
        raise ValueError("Missing scoreboard week")
    week = _int(week_meta.get("number"), 1, 18)
    if expected_week is not None and week != expected_week:
        raise ValueError("Source week does not match request")
    events = payload.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= 24:
        raise ValueError("Unexpected scoreboard event count")
    games: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("Malformed event")
        event_season = event.get("season")
        event_week = event.get("week")
        if (not isinstance(event_season, dict)
            or _int(event_season.get("year"), 2000, 2100) != season
            or not isinstance(event_week, dict)
            or _int(event_week.get("number"), 1, 18) != week):
            raise ValueError("Event season/week disagreement")
        event_id = _text(event.get("id"), 24)
        competitions = event.get("competitions")
        if not event_id or not event_id.isdecimal() or not isinstance(competitions, list) or len(competitions) != 1:
            raise ValueError("Event identity or competition invalid")
        comp = competitions[0]
        if not isinstance(comp, dict) or not isinstance(comp.get("competitors"), list) or len(comp["competitors"]) != 2:
            raise ValueError("Invalid competitors")
        sides: dict[str, dict[str, Any]] = {}
        for team in comp["competitors"]:
            if not isinstance(team, dict) or team.get("homeAway") not in {"home", "away"}:
                raise ValueError("Invalid team position")
            side = team["homeAway"]
            raw_abbr = team.get("team")
            if side in sides or not isinstance(raw_abbr, dict):
                raise ValueError("Duplicate or invalid competitor")
            abbr = _text(raw_abbr.get("abbreviation"), 4)
            if not abbr or not abbr.isalpha() or not abbr.isupper():
                raise ValueError("Invalid team abbreviation")
            score = team.get("score")
            sides[side] = {
                "team": _ALIASES.get(abbr, abbr),
                "score": None if score is None or score == "" else _int(score, 0, 199),
            }
        home, away = sides["home"], sides["away"]
        if home["team"] == away["team"]:
            raise ValueError("Game cannot have identical sides")
        game_id = f"{season}_{week:02d}_{away['team']}_{home['team']}"
        if game_id in seen:
            raise ValueError("Duplicate canonical game")
        seen.add(game_id)
        status = comp.get("status") or event.get("status")
        if not isinstance(status, dict) or not isinstance(status.get("type"), dict):
            raise ValueError("Missing game state")
        state = status["type"].get("state")
        if state not in _ALLOWED:
            raise ValueError("Unexpected game state")
        period = status.get("period")
        if period is not None:
            period = _int(period, 0, 9)
        clock = _text(status.get("displayClock"), 16)
        if state != "pre" and (home["score"] is None or away["score"] is None):
            raise ValueError("In-progress or completed game lacks published scores")
        if state == "pre":
            # Scores equal to 0 in a scheduled event are placeholders, not observed points.
            home["score"] = away["score"] = None
            period = None
            clock = None
        kickoff = _utc(_text(event.get("date"), 48))
        if kickoff is None:
            raise ValueError("Invalid kickoff")
        games.append({
            "game_id": game_id, "provider_event_id": event_id,
            "home_team": home["team"], "away_team": away["team"],
            "home_score": home["score"], "away_score": away["score"],
            "kickoff_utc": kickoff, "state": state,
            "period": period, "clock": clock,
            "status_text": _text(status["type"].get("shortDetail"), 50)
                or _text(status["type"].get("detail"), 50),
            "possession": None, "down": None, "distance": None,
            "play_by_play_available": False, "tracking_available": False,
        })
    games.sort(key=lambda game: (game["kickoff_utc"], game["game_id"]))
    return {"season": season, "week": week, "games": games}


def live_score_pilot(*, season: int = 2026, week: int | None = None,
                     now: datetime | None = None, fetcher=None,
                     enabled: bool | None = None) -> dict[str, Any]:
    """Bounded in-memory polling; hold last good data but explicitly mark stale.

    No persistent raw provider response, redistributable event database, or
    projection/model trust promotion. Cache is per worker for local use only.
    """
    allowed = (os.getenv("PSE_EXPERIMENTAL_LIVE_SCORES") == "1") if enabled is None else enabled
    if not allowed:
        raise PermissionError("Experimental live scoreboard is disabled; opt in locally after reviewing provider access terms")
    if not 2000 <= season <= 2100 or (week is not None and not 1 <= week <= 18):
        raise ValueError("Invalid season/week")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("Current time requires timezone")
    key = (season, week)
    with _LOCK:
        cached = _CACHE.get(key)
        last_attempt = cached["last_attempt"] if cached else None
        throttled = bool(last_attempt and 0 <= (current-last_attempt).total_seconds() < MIN_FETCH_SECONDS)
        error = None
        if not throttled:
            try:
                payload = (fetcher or (lambda: _download(season, week)))()
                normalized = normalize_live_scores(payload, season=season, expected_week=week)
                cached = {"data": normalized, "fetched": current, "last_attempt": current}
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                error = "Provider request failed or failed strict schema validation"
                if cached is not None:
                    cached = {**cached, "last_attempt": current}
                else:
                    raise ValueError(error) from None
            _CACHE[key] = cached
        if cached is None:
            raise ValueError("No qualified live scoreboard snapshot")
        age = max(0, (current-cached["fetched"]).total_seconds())
        return {
            "schema_version": 1,
            "authority": "EXPERIMENTAL_UNLICENSED_SCOREBOARD_EVALUATION",
            "data_mode": "EXPERIMENTAL_LIVE_SCORE_STATUS_ONLY",
            **cached["data"],
            "served_at_utc": current.astimezone(UTC).isoformat(),
            "source": {
                "name": "ESPN Site API, unofficial local evaluation",
                "url": ENDPOINT,
                "fetched_at_utc": cached["fetched"].astimezone(UTC).isoformat(),
                "age_seconds": age,
                "stale": age >= STALE_AFTER_SECONDS or bool(error),
                "throttled": throttled,
                "refresh_error": error,
                "rights_status": "NOT_REVIEWED_FOR_REDISTRIBUTION",
                "official_api_contract": False,
                "live_play_by_play": False,
                "live_tracking": False,
            },
        }
