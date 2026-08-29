from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from player_state_engine.api.nfl_hub_routes import install_nfl_hub_routes
from player_state_engine.product.nfl_hub import (
    HUB_AUTHORITY,
    build_nfl_hub_snapshot,
    canonicalize_rosters,
    load_nfl_hub_snapshot,
    save_nfl_hub_snapshot,
)

NOW = datetime(2026, 8, 29, 3, 0, tzinfo=UTC)


def _rosters() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": 2026,
                "gsis_id": "00-001",
                "full_name": "Alpha Runner",
                "team": "AAA",
                "position": "RB",
                "status_short_description": "Active",
            },
            {
                "season": 2026,
                "gsis_id": "00-002",
                "full_name": "Beta Wideout",
                "team": "BBB",
                "position": "WR",
                "status_short_description": "Active",
            },
        ]
    )


def _depth() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"season": 2026, "gsis_id": "00-001", "team": "AAA", "pos_abb": "RB", "pos_rank": 2},
            {"season": 2026, "gsis_id": "00-002", "team": "BBB", "pos_abb": "WR", "pos_rank": 3},
        ]
    )


def _injuries() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": 2026,
                "gsis_id": "00-001",
                "report_status": "Questionable",
                "practice_status": "Limited",
                "report_primary_injury": "Hamstring",
                "date_modified": "2026-08-28T20:00:00Z",
            }
        ]
    )


def _rankings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "gsis_id": "00-001",
                "rank": 21,
                "adp": 24.0,
                "ecr_type": "ro",
                "page_type": "redraft-overall",
            },
            {
                "gsis_id": "00-002",
                "rank": 45,
                "adp": 48.0,
                "ecr_type": "ro",
                "page_type": "redraft-overall",
            },
        ]
    )


def _projections() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"player_id": "00-001", "valuation_points_q50": 210.0, "vorp": 38.0, "model_version": "m1"},
            {"player_id": "00-002", "valuation_points_q50": 185.0, "vorp": 24.0, "model_version": "m1"},
        ]
    )


def _schedules() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": 2026,
                "game_id": "pre-same-day",
                "game_type": "PRE",
                "week": 4,
                "gameday": "2026-08-29",
                "away_team": "DET",
                "home_team": "IND",
            },
            {
                "season": 2026,
                "game_id": "reg-week-1",
                "game_type": "REG",
                "week": 1,
                "gameday": "2026-09-03",
                "away_team": "AAA",
                "home_team": "BBB",
            },
        ]
    )


def _health(optional_available: bool = True) -> list[dict[str, object]]:
    return [
        {
            "source": "rosters",
            "available": True,
            "required": True,
            "rows": 2,
            "collected_at_utc": NOW.isoformat(),
            "error": None,
        },
        {
            "source": "injuries",
            "available": optional_available,
            "required": False,
            "rows": 1 if optional_available else 0,
            "collected_at_utc": NOW.isoformat(),
            "error": None if optional_available else "source unavailable",
        },
    ]


def test_first_snapshot_is_observational_and_does_not_invent_changes() -> None:
    snapshot = build_nfl_hub_snapshot(
        season=2026,
        rosters=_rosters(),
        depth_charts=_depth(),
        injuries=_injuries(),
        rankings=_rankings(),
        schedules=_schedules(),
        projections=_projections(),
        source_health=_health(),
        generated_at=NOW,
    )
    assert snapshot["authority"] == HUB_AUTHORITY
    assert snapshot["status"] == "READY"
    assert snapshot["event_count"] == 0
    assert snapshot["player_count"] == 2
    assert {game["game_id"] for game in snapshot["upcoming_games"]} == {
        "pre-same-day",
        "reg-week-1",
    }
    player = next(row for row in snapshot["players"] if row["player_id"] == "00-001")
    assert player["projection_q50"] == 210.0
    assert "does not gain authority" in snapshot["model_note"]


def test_snapshot_detects_roster_role_injury_and_market_changes() -> None:
    previous = build_nfl_hub_snapshot(
        season=2026,
        rosters=_rosters(),
        depth_charts=_depth(),
        injuries=_injuries(),
        rankings=_rankings(),
        source_health=_health(),
        generated_at=NOW,
    )
    rosters = _rosters().copy()
    rosters.loc[rosters["gsis_id"].eq("00-001"), "team"] = "CCC"
    rosters.loc[rosters["gsis_id"].eq("00-002"), "status_short_description"] = "Waived"
    rosters = pd.concat(
        [
            rosters,
            pd.DataFrame(
                [
                    {
                        "season": 2026,
                        "gsis_id": "00-003",
                        "full_name": "Gamma Tight End",
                        "team": "DDD",
                        "position": "TE",
                        "status_short_description": "Active",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    depth = _depth().copy()
    depth.loc[depth["gsis_id"].eq("00-001"), "pos_rank"] = 1
    injuries = _injuries().copy()
    injuries.loc[:, "report_status"] = "Out"
    injuries.loc[:, "practice_status"] = "Did Not Participate"
    rankings = _rankings().copy()
    rankings.loc[rankings["gsis_id"].eq("00-001"), "rank"] = 13

    current = build_nfl_hub_snapshot(
        season=2026,
        rosters=rosters,
        depth_charts=depth,
        injuries=injuries,
        rankings=rankings,
        previous_snapshot=previous,
        source_health=_health(),
        generated_at=NOW + timedelta(hours=1),
    )
    types = {event["event_type"] for event in current["events"]}
    assert {
        "TEAM_CHANGED",
        "ROSTER_STATUS_CHANGED",
        "ROSTER_ADDED",
        "DEPTH_CHART_PROMOTION",
        "INJURY_STATUS_CHANGED",
        "MARKET_RANK_RISER",
    }.issubset(types)
    team_event = next(event for event in current["events"] if event["event_type"] == "TEAM_CHANGED")
    assert team_event["authority"] == HUB_AUTHORITY
    assert team_event["before"]["team"] == "AAA"
    assert team_event["after"]["team"] == "CCC"


def test_removed_player_is_explicit_instead_of_silently_disappearing() -> None:
    previous = build_nfl_hub_snapshot(
        season=2026,
        rosters=_rosters(),
        generated_at=NOW,
    )
    current_rosters = _rosters().loc[lambda frame: frame["gsis_id"].ne("00-002")].copy()
    current = build_nfl_hub_snapshot(
        season=2026,
        rosters=current_rosters,
        previous_snapshot=previous,
        generated_at=NOW + timedelta(minutes=30),
    )
    removed = [event for event in current["events"] if event["event_type"] == "ROSTER_REMOVED"]
    assert len(removed) == 1
    assert removed[0]["player_id"] == "00-002"


def test_optional_source_outage_degrades_but_does_not_destroy_roster_truth() -> None:
    snapshot = build_nfl_hub_snapshot(
        season=2026,
        rosters=_rosters(),
        source_health=_health(optional_available=False),
        generated_at=NOW,
    )
    assert snapshot["status"] == "DEGRADED"
    assert snapshot["optional_source_failures"] == ["injuries"]
    assert snapshot["player_count"] == 2


def test_ambiguous_roster_identity_without_temporal_field_fails_closed() -> None:
    rosters = pd.concat([_rosters(), _rosters().iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="ambiguous duplicate player identities"):
        canonicalize_rosters(rosters, season=2026)


def test_snapshot_round_trip_keeps_latest_good_state(tmp_path: Path) -> None:
    snapshot = build_nfl_hub_snapshot(
        season=2026,
        rosters=_rosters(),
        source_health=_health(),
        generated_at=NOW,
    )
    path = save_nfl_hub_snapshot(snapshot, tmp_path)
    assert path == tmp_path / "current.json"
    loaded = load_nfl_hub_snapshot(tmp_path)
    assert loaded is not None
    assert loaded["generated_at_utc"] == NOW.isoformat()
    assert len(list((tmp_path / "snapshots").glob("*.json"))) == 1


def test_api_serves_last_good_snapshot_when_live_refresh_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = build_nfl_hub_snapshot(
        season=2026,
        rosters=_rosters(),
        source_health=_health(),
        generated_at=NOW,
    )
    save_nfl_hub_snapshot(snapshot, tmp_path)

    def fail_refresh(**_: object) -> dict[str, object]:
        raise RuntimeError("network source unavailable")

    monkeypatch.setattr("player_state_engine.api.nfl_hub_routes.refresh_nfl_hub", fail_refresh)
    app = FastAPI()
    install_nfl_hub_routes(app, root=tmp_path)
    client = TestClient(app)
    response = client.get("/v1/nfl/hub?season=2026&refresh=true&max_age_minutes=1440")
    assert response.status_code == 200
    payload = response.json()
    assert payload["player_count"] == 2
    assert payload["cache"]["refreshed_this_request"] is False
    assert "serving the last good snapshot" in payload["refresh_warning"]


def test_api_marks_old_cache_stale(tmp_path: Path) -> None:
    old = build_nfl_hub_snapshot(
        season=2026,
        rosters=_rosters(),
        source_health=_health(),
        generated_at=datetime.now(UTC) - timedelta(hours=2),
    )
    save_nfl_hub_snapshot(old, tmp_path)
    app = FastAPI()
    install_nfl_hub_routes(app, root=tmp_path)
    response = TestClient(app).get("/v1/nfl/hub?season=2026&max_age_minutes=30")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "STALE"
    assert payload["cache"]["stale"] is True
