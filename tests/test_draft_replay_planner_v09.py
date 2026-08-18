from __future__ import annotations

import pandas as pd

from player_state_engine.evaluation.draft_ranking_replay import compare_ranking_policies
from player_state_engine.fantasy.draft_planner import plan_two_turn_draft


def test_historical_replay_rewards_better_candidate_policy() -> None:
    decisions = pd.DataFrame(
        [
            {"draft_id": "d1", "current_pick": 1, "player_id": "a", "base": 90, "challenger": 80, "utility": 4},
            {"draft_id": "d1", "current_pick": 1, "player_id": "b", "base": 80, "challenger": 95, "utility": 9},
            {"draft_id": "d1", "current_pick": 2, "player_id": "c", "base": 91, "challenger": 85, "utility": 3},
            {"draft_id": "d1", "current_pick": 2, "player_id": "d", "base": 82, "challenger": 96, "utility": 8},
        ]
    )
    result = compare_ranking_policies(
        decisions,
        baseline_score="base",
        candidate_score="challenger",
        utility_column="utility",
    )
    assert result["candidate_wins"] is True
    assert result["mean_utility_improvement"] == 5.0
    assert result["mean_oracle_regret_change"] < 0.0


def test_two_turn_planner_values_players_that_will_not_return() -> None:
    board = pd.DataFrame(
        [
            {
                "player_id": "a",
                "player_name": "Take Now",
                "position": "QB",
                "decision_specific_score": 100.0,
                "survival_to_next_pick": 0.05,
            },
            {
                "player_id": "b",
                "player_name": "Likely Returns",
                "position": "WR",
                "decision_specific_score": 90.0,
                "survival_to_next_pick": 0.95,
            },
            {
                "player_id": "c",
                "player_name": "Depth",
                "position": "RB",
                "decision_specific_score": 40.0,
                "survival_to_next_pick": 0.90,
            },
        ]
    )
    plans = plan_two_turn_draft(board, ["a", "b"], simulations=5000, seed=7)
    by_id = {plan.player_id: plan for plan in plans}
    assert by_id["a"].expected_two_pick_value > by_id["b"].expected_two_pick_value
    assert by_id["a"].most_common_next_targets[0]["player_id"] == "b"
    assert by_id["a"].promoted is False
