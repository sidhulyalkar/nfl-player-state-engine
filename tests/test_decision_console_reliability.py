from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from player_state_engine.api.operational import create_app
from player_state_engine.fantasy.decision_audit import build_draft_audit_record
from player_state_engine.fantasy.draft import DraftState
from player_state_engine.fantasy.draft_advisor import build_reliable_live_draft_board
from player_state_engine.fantasy.draft_room import DraftRoomSimulationConfig, simulate_draft_room
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import assess_league_readiness


def _projection_board() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for position, count, base, offset in [
        ("QB", 36, 360.0, 4.0),
        ("RB", 56, 300.0, 1.0),
        ("WR", 72, 290.0, 2.0),
        ("TE", 28, 225.0, 16.0),
    ]:
        for index in range(count):
            median = base - 2.5 * index
            rows.append(
                {
                    "player_id": f"{position}{index + 1}",
                    "player_name": f"{position} {index + 1}",
                    "position": position,
                    "season_points_q10": median - 45.0,
                    "season_points_q50": median,
                    "season_points_q90": median + 50.0,
                    "fantasy_points_ppr_q10": median - 45.0,
                    "fantasy_points_ppr_q50": median,
                    "fantasy_points_ppr_q90": median + 50.0,
                    "market_adp": offset + index * 4.0,
                    "market_adp_sd": 7.0,
                    "availability_probability": 0.98,
                    "opportunity_confidence": 0.80,
                }
            )
    return pd.DataFrame(rows)


def _room_board() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for position in ("QB", "WR"):
        for index in range(20):
            rows.append(
                {
                    "player_id": f"{position}{index}",
                    "position": position,
                    "market_adp": 1.0 + index * 2.0,
                    "market_adp_sd": 5.0,
                    "vorp": 100.0 - index * 3.0,
                    "decision_specific_score": 100.0 - index,
                }
            )
    return pd.DataFrame(rows)


def _league() -> LeagueConfig:
    return LeagueConfig(
        teams=8,
        scoring="ppr",
        roster_slots={"QB": 2, "RB": 3, "WR": 3, "TE": 1, "FLEX": 3, "BENCH": 6},
    )


def _state() -> DraftState:
    return DraftState(
        teams=8,
        draft_slot=4,
        current_pick=12,
        total_rounds=18,
        drafted_player_ids=("RB1", "WR1", "QB1"),
        roster_player_ids=("QB1",),
    )


def test_draft_room_reproducible_and_format_sensitive() -> None:
    board = _room_board()
    one_qb = LeagueConfig(
        teams=8,
        roster_slots={"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 2},
    )
    two_qb = LeagueConfig(
        teams=8,
        roster_slots={"QB": 2, "RB": 2, "WR": 3, "TE": 1, "FLEX": 2},
    )
    cfg = DraftRoomSimulationConfig(simulations=1000, seed=77, position_need_strength=1.5)
    first = simulate_draft_room(board, one_qb, current_pick=8, next_pick=21, simulation=cfg)
    repeat = simulate_draft_room(board, one_qb, current_pick=8, next_pick=21, simulation=cfg)
    two = simulate_draft_room(board, two_qb, current_pick=8, next_pick=21, simulation=cfg)
    assert np.allclose(first["room_survival_to_next_pick"], repeat["room_survival_to_next_pick"])
    assert first["room_survival_to_next_pick"].between(0, 1).all()
    assert (
        two.loc[two.position.eq("QB"), "room_survival_to_next_pick"].mean()
        < first.loc[first.position.eq("QB"), "room_survival_to_next_pick"].mean()
    )


def test_reliable_board_exposes_guardrails_without_promoting_challenger() -> None:
    board = build_reliable_live_draft_board(
        _projection_board(),
        _league(),
        _state(),
        room_simulations=250,
        room_seed=9,
        projection_age_hours=2.0,
    )
    assert {
        "guarded_draft_action",
        "room_survival_to_next_pick",
        "room_challenger_score",
        "draft_reliability_score",
        "draft_reliability_reasons",
        "projection_freshness_status",
    }.issubset(board.columns)
    assert board["draft_reliability_score"].between(0, 100).all()
    assert not board["room_challenger_promoted"].any()


def test_stale_projection_forces_verify() -> None:
    board = build_reliable_live_draft_board(
        _projection_board(),
        _league(),
        _state(),
        room_simulations=200,
        room_seed=10,
        projection_age_hours=72.0,
        max_projection_age_hours=24.0,
    )
    assert set(board["projection_freshness_status"]) == {"STALE"}
    assert set(board["guarded_draft_action"]) == {"VERIFY"}


def test_readiness_and_decision_audit_are_decision_time_safe() -> None:
    projections = _projection_board()
    readiness = assess_league_readiness(projections, _league())
    assert readiness.projection_rows == len(projections)
    assert readiness.unique_player_coverage == 1.0
    assert 0.0 <= readiness.score <= 100.0

    board = build_reliable_live_draft_board(
        projections,
        _league(),
        _state(),
        room_simulations=150,
        room_seed=12,
        projection_age_hours=1.0,
    )
    record = build_draft_audit_record(
        board,
        _state(),
        _league(),
        league_key="test-league",
        recorded_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
    )
    assert record.recommendation_player_id == str(board.iloc[0]["player_id"])
    assert record.context["current_pick"] == 12
    assert len(record.candidates) == 10


def test_operational_api_installs_reliable_board_route() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/v1/leagues/{league_id}/draft/reliable-board" in paths
