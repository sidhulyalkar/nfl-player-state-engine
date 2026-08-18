from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from fastapi.testclient import TestClient

from player_state_engine.api.operational import create_app
from player_state_engine.data.io import write_table
from player_state_engine.fantasy.rankings import normalize_ranking_frame
from player_state_engine.product.schemas import (
    FantasyRoster,
    LeagueIdentity,
    LeagueSettings,
    LeagueSnapshot,
)
from player_state_engine.product.store import LeagueSnapshotStore


def _projections() -> pd.DataFrame:
    rows = [
        ("qb1", "QB One", "QB", 250.0, 350.0, 450.0, 1.5),
        ("qb2", "QB Two", "QB", 230.0, 330.0, 420.0, 3.0),
        ("rb1", "RB One", "RB", 180.0, 280.0, 380.0, 2.5),
        ("rb2", "RB Two", "RB", 160.0, 250.0, 340.0, 6.0),
        ("wr1", "WR One", "WR", 170.0, 270.0, 370.0, 4.0),
        ("te1", "TE One", "TE", 120.0, 210.0, 300.0, 10.0),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "player_id",
            "player_name",
            "position",
            "season_points_q10",
            "season_points_q50",
            "season_points_q90",
            "market_adp",
        ],
    )


def _snapshot() -> LeagueSnapshot:
    return LeagueSnapshot(
        identity=LeagueIdentity(
            league_id="league-v09",
            platform="manual",
            name="v0.9 API Test",
            season=2026,
            imported_at=datetime.now(UTC),
        ),
        settings=LeagueSettings(
            teams=4,
            season=2026,
            scoring={"rec": 1.0},
            roster_positions=["QB", "QB", "RB", "WR", "TE", "BENCH", "BENCH"],
            draft_type="snake",
        ),
        rosters=[FantasyRoster(roster_id="1", team_name="My Team")],
        metadata={
            "external_roster_id": "1",
            "active_draft": {"status": "drafting", "settings": {"rounds": 7}},
            "live_draft_picks": [],
        },
    )


def test_operational_api_exposes_ranking_audit_and_unpromoted_plan(tmp_path) -> None:
    store_root = tmp_path / "leagues"
    projections_path = tmp_path / "projections.csv"
    ranking_root = tmp_path / "rankings"
    LeagueSnapshotStore(store_root).save(_snapshot())
    _projections().to_csv(projections_path, index=False)

    rankings = normalize_ranking_frame(
        pd.DataFrame(
            {
                "player_id": ["qb1", "qb2", "rb1", "wr1"],
                "player_name": ["QB One", "QB Two", "RB One", "WR One"],
                "position": ["QB", "QB", "RB", "WR"],
                "rank": [1, 2, 5, 4],
            }
        ),
        source="fantasypros_ecr",
        scoring="ppr",
        teams=4,
        qb_format_name="2qb",
        captured_at_utc="2026-08-17T20:00:00Z",
    )
    write_table(rankings, ranking_root / "fantasypros" / "snapshot.parquet")

    app = create_app(
        store_root=store_root,
        projections_path=projections_path,
        ranking_root=ranking_root,
    )
    client = TestClient(app)

    sources = client.get("/v1/rankings/sources")
    assert sources.status_code == 200
    source_payload = sources.json()
    assert source_payload["external_values_are_audit_only"] is True
    assert any(row["source"] == "fantasypros_ecr" for row in source_payload["installed"])

    audit = client.get("/v1/leagues/league-v09/rankings/audit")
    assert audit.status_code == 200
    audit_payload = audit.json()
    assert audit_payload["format"]["qb_format"] == "2qb"
    assert audit_payload["ranking_context"]["external_values_are_audit_only"] is True
    assert audit_payload["ranking_context"]["matched_rows"] >= 4
    assert audit_payload["scoring_status"]["scoring_exact"] is False
    assert audit_payload["scoring_status"]["fallback_share"] == 1.0

    board = client.get(
        "/v1/leagues/league-v09/draft/board",
        params={"roster_id": "1", "draft_slot": 1, "refresh": False},
    )
    assert board.status_code == 200
    board_rows = board.json()["board"]
    assert board_rows
    candidate_ids = [row["player_id"] for row in board_rows[:2]]

    plan = client.post(
        "/v1/leagues/league-v09/draft/plan",
        json={
            "roster_id": "1",
            "player_ids": candidate_ids,
            "draft_slot": 1,
            "refresh": False,
            "simulations": 300,
        },
    )
    assert plan.status_code == 200
    plan_payload = plan.json()
    assert plan_payload["promoted"] is False
    assert plan_payload["model_source"] == "two_turn_survival_lookahead_research_v1"
    assert len(plan_payload["plans"]) == 2
