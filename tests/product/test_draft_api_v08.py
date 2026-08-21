from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from player_state_engine.api.operational import create_app
from player_state_engine.product.schemas import (
    FantasyRoster,
    LeagueIdentity,
    LeagueSettings,
    LeagueSnapshot,
    RosterEntry,
)
from player_state_engine.product.store import LeagueSnapshotStore


def _projections() -> pd.DataFrame:
    rows = []
    for position, count, base in [
        ("QB", 28, 360),
        ("RB", 40, 300),
        ("WR", 50, 290),
        ("TE", 20, 220),
    ]:
        for index in range(count):
            median = base - index * 4
            rows.append(
                {
                    "player_id": f"{position}{index + 1}",
                    "player_name": f"{position} {index + 1}",
                    "position": position,
                    "season_points_q10": median - 45,
                    "season_points_q50": median,
                    "season_points_q90": median + 50,
                    "market_adp": index * 3
                    + {"QB": 3, "RB": 1, "WR": 2, "TE": 16}[position],
                    "availability_probability": 0.98,
                    "opportunity_confidence": 0.8,
                    "model_version": "test-v1",
                    "prediction_timestamp": "2026-08-17T12:00:00Z",
                    "source_cutoff": "2026-08-17T11:00:00Z",
                    "data_mode": "LIVE_OFFICIAL",
                }
            )
    return pd.DataFrame(rows)


def test_draft_board_and_compare_are_server_side_and_2qb_aware(tmp_path) -> None:
    store_root = tmp_path / "leagues"
    projections_path = tmp_path / "projections.csv"
    _projections().to_csv(projections_path, index=False)
    snapshot = LeagueSnapshot(
        identity=LeagueIdentity(
            league_id="L1",
            platform="sleeper",
            name="Two QB Test",
            season=2026,
            external_user_id="me",
        ),
        settings=LeagueSettings(
            teams=8,
            season=2026,
            scoring={"rec": 1.0},
            roster_positions=[
                "QB",
                "QB",
                "RB",
                "RB",
                "WR",
                "WR",
                "TE",
                "FLEX",
                "BN",
                "BN",
            ],
            draft_type="snake",
        ),
        rosters=[
            FantasyRoster(
                roster_id="1",
                manager_id="me",
                team_name="My Team",
                players=[
                    RosterEntry(
                        platform_player_id="s-qb1",
                        canonical_player_id="QB1",
                        player_name="QB 1",
                        position="QB",
                    )
                ],
            )
        ],
        metadata={
            "external_roster_id": "1",
            "active_draft": {
                "status": "drafting",
                "type": "snake",
                "draft_order": {"me": 2},
                "settings": {"rounds": 10},
            },
            "live_draft_picks": [
                {
                    "pick_no": 1,
                    "player_id": "RB1",
                    "player_name": "RB 1",
                    "position": "RB",
                    "roster_id": "2",
                }
            ],
        },
    )
    LeagueSnapshotStore(store_root).save(snapshot)
    app = create_app(store_root=store_root, projections_path=projections_path)
    client = TestClient(app)

    board_response = client.get(
        "/v1/leagues/L1/draft/board",
        params={"roster_id": "1", "refresh": "false"},
    )
    assert board_response.status_code == 200
    board = board_response.json()
    assert board["league"]["format_label"].startswith("8T • 2QB")
    assert board["draft_state"]["current_pick"] == 2
    assert board["draft_state"]["draft_slot"] == 2
    assert board["survival_model"]["source"] == "normal_adp_fallback"
    assert all(row["player_id"] != "RB1" for row in board["board"])

    reliable_response = client.get(
        "/v1/leagues/L1/draft/reliable-board",
        params={
            "roster_id": "1",
            "refresh": "false",
            "room_simulations": 120,
            "max_projection_age_hours": 24,
        },
    )
    assert reliable_response.status_code == 200
    reliable = reliable_response.json()
    assert reliable["readiness"]["ready"] is True
    assert reliable["survival_model"]["source"] == "normal_adp_fallback"
    assert reliable["research"]["baseline_survival_authoritative"] is True
    assert reliable["research"]["room_challenger_promoted"] is False
    reliable_by_id = {row["player_id"]: row for row in reliable["board"]}
    baseline_by_id = {row["player_id"]: row for row in board["board"]}
    qb2 = reliable_by_id["QB2"]
    assert qb2["survival_to_next_pick"] == baseline_by_id["QB2"]["survival_to_next_pick"]
    assert "room_survival_to_next_pick" in qb2
    assert "draft_reliability_score" in qb2
    assert qb2["room_challenger_promoted"] is False

    compare_response = client.post(
        "/v1/leagues/L1/draft/compare",
        json={
            "roster_id": "1",
            "player_ids": ["QB2", "WR1"],
            "refresh": False,
            "simulations": 120,
        },
    )
    assert compare_response.status_code == 200
    comparison = compare_response.json()
    assert len(comparison["candidates"]) == 2
    qb = next(row for row in comparison["candidates"] if row["player_id"] == "QB2")
    assert qb["roster_impact"]["projected_slot"] == "QB2"
    assert comparison["winners"]["best_pick_now"] in {"QB2", "WR1"}
