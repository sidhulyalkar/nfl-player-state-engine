from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.roster_simulator import evaluate_candidate_impacts


def test_2qb_counterfactual_rewards_missing_second_starting_quarterback() -> None:
    frame = pd.DataFrame(
        [
            {"player_id": "qb1", "player_name": "QB One", "position": "QB", "season_points_q10": 260, "season_points_q50": 320, "season_points_q90": 380},
            {"player_id": "rb1", "player_name": "RB One", "position": "RB", "season_points_q10": 180, "season_points_q50": 230, "season_points_q90": 280},
            {"player_id": "rb2", "player_name": "RB Two", "position": "RB", "season_points_q10": 170, "season_points_q50": 220, "season_points_q90": 270},
            {"player_id": "wr1", "player_name": "WR One", "position": "WR", "season_points_q10": 175, "season_points_q50": 225, "season_points_q90": 275},
            {"player_id": "wr2", "player_name": "WR Two", "position": "WR", "season_points_q10": 165, "season_points_q50": 215, "season_points_q90": 265},
            {"player_id": "te1", "player_name": "TE One", "position": "TE", "season_points_q10": 120, "season_points_q50": 170, "season_points_q90": 220},
            {"player_id": "qb2", "player_name": "QB Two", "position": "QB", "season_points_q10": 230, "season_points_q50": 290, "season_points_q90": 350},
            {"player_id": "wr3", "player_name": "WR Three", "position": "WR", "season_points_q10": 160, "season_points_q50": 205, "season_points_q90": 250},
        ]
    )
    config = LeagueConfig(
        teams=8,
        roster_slots={"QB": 2, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
    )
    roster = ["qb1", "rb1", "rb2", "wr1", "wr2", "te1"]
    impacts = evaluate_candidate_impacts(
        frame, config, roster, ["qb2", "wr3"], simulations=150, seed=7
    )
    by_id = {impact.player_id: impact for impact in impacts}
    assert by_id["qb2"].projected_slot == "QB2"
    assert by_id["qb2"].marginal_median > by_id["wr3"].marginal_median
    assert by_id["qb2"].roster_fit_score > by_id["wr3"].roster_fit_score
