from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.draft import (
    DraftState,
    build_live_draft_board,
    probability_available_at_pick,
)
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.valuation import replacement_ranks, starter_allocation


def _projections() -> pd.DataFrame:
    rows = []
    for position, count, base in [
        ("QB", 40, 360),
        ("RB", 70, 300),
        ("WR", 90, 290),
        ("TE", 35, 220),
    ]:
        for idx in range(count):
            q50 = base - idx * (5 if position == "QB" else 3)
            rows.append(
                {
                    "player_id": f"{position}{idx+1}",
                    "player_name": f"{position} {idx+1}",
                    "position": position,
                    "season_points_q10": q50 - 55,
                    "season_points_q50": q50,
                    "season_points_q90": q50 + 60,
                    "market_adp": idx * 4 + {"QB": 6, "RB": 1, "WR": 2, "TE": 20}[position],
                    "availability_probability": 0.98,
                    "opportunity_confidence": 0.75,
                }
            )
    return pd.DataFrame(rows)


def test_expanded_8_team_format_creates_real_2qb_and_three_flex_demand() -> None:
    frame = _projections()
    normal = LeagueConfig(teams=8, roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1})
    expanded = LeagueConfig(
        teams=8,
        roster_slots={"QB": 2, "RB": 3, "WR": 3, "TE": 1, "FLEX": 3, "DEF": 1, "K": 1},
    )
    normal_starters = starter_allocation(frame, normal)
    expanded_starters = starter_allocation(frame, expanded)
    assert normal_starters["QB"] == 8
    assert expanded_starters["QB"] == 16
    assert sum(expanded_starters.get(p, 0) for p in ("RB", "WR", "TE")) == 80
    normal_replacement = replacement_ranks(frame, normal)
    expanded_replacement = replacement_ranks(frame, expanded)
    assert expanded_replacement["QB"] > normal_replacement["QB"]
    assert expanded_replacement["RB"] > normal_replacement["RB"]


def test_live_board_removes_drafted_players_and_uses_next_pick_survival() -> None:
    frame = _projections()
    config = LeagueConfig(
        teams=8,
        roster_slots={"QB": 2, "RB": 3, "WR": 3, "TE": 1, "FLEX": 3},
    )
    state = DraftState(
        teams=8,
        draft_slot=3,
        current_pick=11,
        total_rounds=18,
        drafted_player_ids=("RB1", "WR1"),
        roster_player_ids=("QB1",),
    )
    board = build_live_draft_board(frame, config, state)
    assert "RB1" not in set(board.player_id)
    assert "WR1" not in set(board.player_id)
    assert board.next_pick.nunique() == 1
    assert int(board.next_pick.iloc[0]) == 14
    assert board["survival_to_next_pick"].between(0, 1).all()
    assert board["live_draft_score"].between(0, 100).all()
    assert set(board["draft_action"]).issubset({"DRAFT NOW", "TARGET", "WAIT", "CONSIDER"})


def test_probability_available_behaves_in_the_right_direction() -> None:
    assert probability_available_at_pick(50, 20, 8) > 0.99
    assert probability_available_at_pick(10, 30, 8) < 0.01
