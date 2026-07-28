import pandas as pd

from player_state_engine.fantasy.decision_board import DecisionType, build_decision_board
from player_state_engine.fantasy.league import LeagueConfig


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": ["a", "b", "c", "d"],
            "player_name": ["A", "B", "C", "D"],
            "position": ["RB", "RB", "WR", "WR"],
            "season_points_q10": [130, 100, 120, 90],
            "season_points_q50": [210, 180, 205, 160],
            "season_points_q90": [300, 310, 270, 280],
            "availability_probability": [0.98, 0.75, 0.99, 0.95],
            "opportunity_confidence": [0.8, 0.5, 0.7, 0.4],
            "role_growth_score": [0.1, 0.9, 0.2, 0.8],
            "prospect_prior_score": [0.1, 0.8, 0.2, 0.7],
            "breakout_probability": [0.1, 0.7, 0.2, 0.6],
            "market_cost": [40, 10, 35, 8],
            "age": [27, 22, 26, 21],
        }
    )


def test_decision_boards_are_decision_specific() -> None:
    cfg = LeagueConfig()
    draft = build_decision_board(_frame(), cfg, DecisionType.DRAFT)
    stash = build_decision_board(_frame(), cfg, DecisionType.STASH)
    assert set(draft["decision_type"]) == {"draft"}
    assert set(stash["decision_type"]) == {"stash"}
    assert draft.iloc[0]["player_id"] != stash.iloc[0]["player_id"]
    assert stash["decision_reasons"].notna().all()
