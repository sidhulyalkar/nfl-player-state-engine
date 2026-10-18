from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from player_state_engine.product.sunday_board import (
    build_sunday_board,
    normalize_schedule,
    refresh_schedule,
)


def game(
    idx: int, *,
    week: int = 7,
    home_score: str = "",
    away_score: str = "",
    date: str = "2026-10-18",
) -> dict[str, str]:
    return {
        "game_id": f"2026_{week:02d}_AAA_BBB" if idx == 0 else f"2026_{week:02d}_T{idx:02d}_U{idx:02d}",
        "season": "2026",
        "week": str(week),
        "game_type": "REG",
        "gameday": date,
        "gametime": "13:00",
        "away_team": "AAA" if idx == 0 else f"T{idx:02d}",
        "home_team": "BBB" if idx == 0 else f"U{idx:02d}",
        "home_score": home_score,
        "away_score": away_score,
    }


def fixture_bytes(*, home_score: str = "", away_score: str = "") -> bytes:
    values = [game(0, home_score=home_score, away_score=away_score)]
    values.extend(game(i, week=5, date="2026-10-04") for i in range(1, 60))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(values[0]))
    writer.writeheader()
    writer.writerows(values)
    return output.getvalue().encode("utf-8")


def test_public_snapshot_refresh_and_week_selector(tmp_path: Path) -> None:
    now = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)
    calls = 0

    def fetcher() -> bytes:
        nonlocal calls
        calls += 1
        return fixture_bytes(home_score="17", away_score="14")

    board = build_sunday_board(
        root=tmp_path, season=2026, now=now, refresh=True, fetcher=fetcher,
    )
    assert board["authority"] == "PUBLIC_SCHEDULE_NOT_LIVE_PBP"
    assert board["tracking_fidelity"] == "NO_TRACKING"
    assert board["week"] == 7
    assert len(board["games"]) == 1
    assert board["games"][0]["score_state"] == "PUBLISHED_UNVERIFIED"
    assert board["games"][0]["play_by_play_available"] is False
    assert board["games"][0]["home_score"] == 17
    assert board["games"][0]["quarter"] is None
    assert board["source"]["integrity_verified"] is True
    assert calls == 1

    repeat = build_sunday_board(
        root=tmp_path,
        season=2026,
        now=now + timedelta(seconds=120),
        refresh=True,
        fetcher=fetcher,
    )
    assert repeat["source"]["refresh"]["throttled"] is True
    assert calls == 1


def test_missing_score_not_confused_with_live_zero(tmp_path: Path) -> None:
    now = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)
    board = build_sunday_board(
        root=tmp_path, season=2026, now=now,
        refresh=True, fetcher=fixture_bytes,
    )
    match = board["games"][0]
    assert match["away_score"] is None
    assert match["home_score"] is None
    assert match["score_state"] == "NOT_PUBLISHED"


def test_last_good_snapshot_retained_when_fetch_fails(tmp_path: Path) -> None:
    now = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)
    build_sunday_board(
        root=tmp_path, season=2026, now=now,
        refresh=True, fetcher=lambda: fixture_bytes(home_score="7", away_score="0"),
    )

    def failing() -> bytes:
        raise OSError("provider offline")

    board = build_sunday_board(
        root=tmp_path, season=2026,
        now=now + timedelta(seconds=601), refresh=True, fetcher=failing,
    )
    assert "provider offline" in board["source"]["refresh"]["error"]
    assert board["source"]["stale"] is True
    assert board["games"][0]["home_score"] == 7


def test_cache_tampering_fails_closed(tmp_path: Path) -> None:
    now = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)
    build_sunday_board(
        root=tmp_path, season=2026, now=now, refresh=True, fetcher=fixture_bytes,
    )
    (tmp_path / "games.csv").write_text("season,week\n2026,7\n", encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        build_sunday_board(root=tmp_path, season=2026, now=now)


def test_weeks_never_come_from_unverified_demo_csv() -> None:
    now = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)
    data = normalize_schedule(
        [game(0, home_score="2", away_score="3")],
        season=2026, now=now,
    )
    assert data["week"] == 7
    assert len(data["games"]) == 1
    assert data["games"][0]["possession"] is None


def test_invalid_schema_preserves_last_good(tmp_path: Path) -> None:
    now = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)
    good = fixture_bytes()
    assert refresh_schedule(tmp_path, now=now, fetcher=lambda: good)["refreshed"]

    bad = b"game_id,away_team\nX,Y\n"
    result = refresh_schedule(
        tmp_path, now=now + timedelta(seconds=601), fetcher=lambda: bad,
    )
    assert result["refreshed"] is False
    assert "missing required fields" in str(result["error"])
    assert (tmp_path / "games.csv").read_bytes() == good
