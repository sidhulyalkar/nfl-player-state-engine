"""Contract tests for optional read-only NFL live-score experiment."""
from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest

from player_state_engine.product.experimental_live_scores import (
    _CACHE,
    live_score_pilot,
    normalize_live_scores,
)


def fixture(state: str = "in", away_score: str = "7", home_score: str = "10") -> dict:
    return {
        "season": {"year": 2026, "type": 2},
        "week": {"number": 7},
        "events": [{
            "id": "401899999",
            "date": "2026-10-25T20:25:00Z",
            "season": {"year": 2026, "type": 2},
            "week": {"number": 7},
            "competitions": [{
                "competitors": [
                    {"homeAway": "away", "team": {"abbreviation": "GB"},
                     "score": away_score},
                    {"homeAway": "home", "team": {"abbreviation": "DET"},
                     "score": home_score},
                ],
                "status": {"type": {"state": state, "shortDetail": "2nd 12:53"},
                           "displayClock": "12:53", "period": 2},
            }],
        }],
    }


@pytest.fixture(autouse=True)
def clear_cache():
    _CACHE.clear()
    yield
    _CACHE.clear()


def test_normalized_live_game_uses_source_score_clock_and_status():
    result = normalize_live_scores(fixture(), season=2026, expected_week=7)
    assert result["games"][0]["game_id"] == "2026_07_GB_DET"
    game = result["games"][0]
    assert (game["away_score"], game["home_score"]) == (7, 10)
    assert (game["period"], game["clock"], game["state"]) == (2, "12:53", "in")
    assert game["possession"] is None
    assert game["play_by_play_available"] is False
    assert game["tracking_available"] is False


def test_pre_kickoff_zero_is_never_reported_as_real_score():
    game = normalize_live_scores(fixture("pre", "0", "0"), season=2026)["games"][0]
    assert game["home_score"] is None
    assert game["away_score"] is None
    assert game["period"] is None
    assert game["clock"] is None


def test_invalid_identity_week_and_duplicate_games_fail_closed():
    p = fixture()
    p["events"][0]["week"]["number"] = 8
    with pytest.raises(ValueError, match="season/week"):
        normalize_live_scores(p, season=2026, expected_week=7)
    p = fixture()
    p["events"].append(copy.deepcopy(p["events"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        normalize_live_scores(p, season=2026)


def test_bad_score_and_unknown_state_are_not_rendered_as_live():
    p = fixture()
    p["events"][0]["competitions"][0]["competitors"][0]["score"] = "invalid"
    with pytest.raises(ValueError, match="integer"):
        normalize_live_scores(p, season=2026)
    p = fixture("suspended")
    with pytest.raises(ValueError, match="state"):
        normalize_live_scores(p, season=2026)
    p = fixture("in", "", "0")
    with pytest.raises(ValueError, match="scores"):
        normalize_live_scores(p, season=2026)


def test_opt_in_required_even_when_fixture_provided():
    with pytest.raises(PermissionError, match="disabled"):
        live_score_pilot(enabled=False, season=2026, week=7, fetcher=fixture)


def test_cache_enforces_poll_rate_and_reports_source_freshness():
    t = datetime(2026, 10, 25, 21, 0, tzinfo=UTC)
    calls = 0

    def fetcher():
        nonlocal calls
        calls += 1
        return fixture()

    first = live_score_pilot(season=2026, week=7, now=t, enabled=True,
                             fetcher=fetcher)
    assert first["source"]["stale"] is False
    assert first["authority"] == "EXPERIMENTAL_UNLICENSED_SCOREBOARD_EVALUATION"
    repeat = live_score_pilot(season=2026, week=7,
                              now=t + timedelta(seconds=12), enabled=True,
                              fetcher=fetcher)
    assert calls == 1
    assert repeat["source"]["throttled"] is True
    assert repeat["source"]["age_seconds"] == 12


def test_network_failure_stays_stale_without_inventing_new_points():
    t = datetime(2026, 10, 25, 21, 0, tzinfo=UTC)
    first = live_score_pilot(season=2026, week=7, now=t, enabled=True,
                             fetcher=fixture)

    def fail():
        raise OSError("do not expose private transport details")

    second = live_score_pilot(season=2026, week=7,
                              now=t + timedelta(seconds=125), enabled=True,
                              fetcher=fail)
    assert second["source"]["stale"] is True
    assert "transport" not in str(second)
    assert second["games"] == first["games"]


def test_initial_network_failure_rejects_empty_false_success():
    with pytest.raises(ValueError, match="Provider request failed"):
        live_score_pilot(season=2026, week=7, now=datetime.now(UTC),
                         enabled=True, fetcher=lambda: {})


def test_team_alias_preserves_nflverse_canonical_game_id():
    p = fixture()
    p["events"][0]["competitions"][0]["competitors"][0]["team"]["abbreviation"] = "LAR"
    normalized = normalize_live_scores(p, season=2026)
    assert normalized["games"][0]["away_team"] == "LA"
    assert normalized["games"][0]["game_id"] == "2026_07_LA_DET"


def test_clock_and_state_cannot_be_inferred_from_missing_provider_fields():
    p = fixture()
    p["events"][0]["competitions"][0]["status"]["type"]["state"] = None
    with pytest.raises(ValueError, match="state"):
        normalize_live_scores(p, season=2026)
