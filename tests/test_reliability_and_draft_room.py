from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from player_state_engine.fantasy.draft import DraftState
from player_state_engine.fantasy.draft_advisor import build_reliable_live_draft_board
from player_state_engine.fantasy.draft_room import DraftRoomSimulationConfig, simulate_draft_room
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.player_state.core import RolePosterior, StateEstimate
from player_state_engine.player_state.graph import (
    ExecutionState,
    PlayerStateSnapshot,
    TeamVolumeState,
    UncertaintyBreakdown,
)
from player_state_engine.player_state.insights import build_player_intelligence_card
from player_state_engine.player_state.trust import assess_forecast_trust


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
                    "market_adp": offset + index * 4.0,
                    "market_adp_sd": 7.0,
                    "availability_probability": 0.98,
                    "opportunity_confidence": 0.80,
                }
            )
    return pd.DataFrame(rows)


def _room_board() -> pd.DataFrame:
    rows = []
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


def _draft_state() -> DraftState:
    return DraftState(
        teams=8,
        draft_slot=4,
        current_pick=12,
        total_rounds=18,
        drafted_player_ids=("RB1", "WR1", "QB1"),
        roster_player_ids=("QB1",),
    )


def _draft_league() -> LeagueConfig:
    return LeagueConfig(
        teams=8,
        scoring="ppr",
        roster_slots={"QB": 2, "RB": 3, "WR": 3, "TE": 1, "FLEX": 3, "BENCH": 6},
    )


def _role(now: datetime) -> RolePosterior:
    def state(mean: float) -> StateEstimate:
        return StateEstimate(
            mean,
            max(0.0, mean - 0.08),
            mean,
            min(1.0, mean + 0.08),
            40.0,
            0.90,
            0.05,
        )

    return RolePosterior(
        player_id="WR1",
        position="WR",
        as_of=now,
        states={
            "route_participation": state(0.86),
            "target_share": state(0.24),
            "carry_share": state(0.02),
            "red_zone_share": state(0.22),
            "goal_line_share": state(0.06),
        },
        role_change_probability=0.05,
        maturity=0.90,
        role_label="established_featured",
        evidence_rows=20,
    )


def _snapshot(now: datetime) -> PlayerStateSnapshot:
    return PlayerStateSnapshot(
        player_id="WR1",
        position="WR",
        role=_role(now),
        team_volume=TeamVolumeState(36.0, 4.0, 25.0, 4.0),
        execution=ExecutionState(catch_rate=0.70, yards_per_reception=12.0),
        p_active=0.98,
    )


def test_draft_room_is_reproducible_and_correlated() -> None:
    board = _room_board()
    league = LeagueConfig(teams=8, roster_slots={"QB": 2, "RB": 2, "WR": 3, "TE": 1, "FLEX": 2})
    cfg = DraftRoomSimulationConfig(simulations=500, seed=123, position_need_strength=0.8)
    first = simulate_draft_room(board, league, current_pick=8, next_pick=17, simulation=cfg)
    second = simulate_draft_room(board, league, current_pick=8, next_pick=17, simulation=cfg)
    assert np.allclose(first["room_survival_to_next_pick"], second["room_survival_to_next_pick"])
    assert first["room_survival_to_next_pick"].between(0, 1).all()
    early = float(first.loc[first.player_id.eq("QB0"), "room_survival_to_next_pick"].iloc[0])
    late = float(first.loc[first.player_id.eq("QB15"), "room_survival_to_next_pick"].iloc[0])
    assert early < late


def test_two_qb_format_increases_qb_room_pressure() -> None:
    board = _room_board()
    one_qb = LeagueConfig(teams=8, roster_slots={"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 2})
    two_qb = LeagueConfig(teams=8, roster_slots={"QB": 2, "RB": 2, "WR": 3, "TE": 1, "FLEX": 2})
    cfg = DraftRoomSimulationConfig(simulations=1200, seed=77, position_need_strength=1.5)
    one = simulate_draft_room(board, one_qb, current_pick=8, next_pick=21, simulation=cfg)
    two = simulate_draft_room(board, two_qb, current_pick=8, next_pick=21, simulation=cfg)
    one_qb_survival = one.loc[one.position.eq("QB"), "room_survival_to_next_pick"].mean()
    two_qb_survival = two.loc[two.position.eq("QB"), "room_survival_to_next_pick"].mean()
    assert two_qb_survival < one_qb_survival


def test_reliable_draft_board_preserves_baseline_and_exposes_guardrails() -> None:
    board = build_reliable_live_draft_board(
        _projection_board(),
        _draft_league(),
        _draft_state(),
        room_simulations=300,
        room_seed=9,
        projection_age_hours=2.0,
    )
    required = {
        "draft_action",
        "guarded_draft_action",
        "room_survival_to_next_pick",
        "room_challenger_score",
        "room_rank",
        "draft_reliability_score",
        "draft_reliability_reasons",
        "projection_freshness_status",
    }
    assert required.issubset(board.columns)
    assert board["room_challenger_score"].between(0, 100).all()
    assert board["draft_reliability_score"].between(0, 100).all()
    assert set(board["guarded_draft_action"]).issubset(
        {"DRAFT NOW", "TARGET", "WAIT", "CONSIDER", "VERIFY"}
    )
    assert set(board["projection_freshness_status"]) == {"FRESH"}
    assert not board["room_challenger_promoted"].any()


def test_stale_projection_artifact_forces_verify_without_overwriting_baseline_action() -> None:
    board = build_reliable_live_draft_board(
        _projection_board(),
        _draft_league(),
        _draft_state(),
        room_simulations=250,
        room_seed=10,
        projection_age_hours=72.0,
        max_projection_age_hours=24.0,
    )
    assert set(board["projection_freshness_status"]) == {"STALE"}
    assert board["projection_freshness_hard_fail"].all()
    assert set(board["guarded_draft_action"]) == {"VERIFY"}
    assert board["draft_action"].ne("VERIFY").any()
    assert board["draft_reliability_reasons"].str.contains("stale").all()


def test_forecast_trust_penalizes_stale_evidence_without_calling_player_bad() -> None:
    now = datetime(2026, 8, 20, 16, 0, tzinfo=UTC)
    snapshot = _snapshot(now)
    draws = pd.DataFrame(
        {
            "league_fantasy_points": np.linspace(10.0, 20.0, 1000),
            "routes": np.full(1000, 30.0),
            "targets": np.full(1000, 8.0),
            "carries": np.zeros(1000),
            "team_red_zone_plays": np.full(1000, 7.0),
        }
    )
    uncertainty = UncertaintyBreakdown(
        total_variance=18.0,
        availability=0.10,
        team_volume=0.20,
        role_opportunity=0.30,
        execution=0.20,
        environment=0.10,
        residual_model=0.10,
    )
    fresh_card = build_player_intelligence_card(
        snapshot,
        draws,
        uncertainty,
        consensus_median=15.5,
        evidence_freshness=now - timedelta(hours=1),
    )
    stale_card = build_player_intelligence_card(
        snapshot,
        draws,
        uncertainty,
        consensus_median=15.5,
        evidence_freshness=now - timedelta(hours=200),
    )
    fresh = assess_forecast_trust(snapshot, draws, uncertainty, fresh_card, as_of=now)
    stale = assess_forecast_trust(snapshot, draws, uncertainty, stale_card, as_of=now)
    assert fresh.score > stale.score
    assert fresh.action_policy in {"ACT", "LEAN"}
    assert stale.action_policy == "VERIFY_DATA"
    assert "STALE_EVIDENCE" in stale.flags
