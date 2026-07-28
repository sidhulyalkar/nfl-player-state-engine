from __future__ import annotations

import pandas as pd

from player_state_engine.evaluation.market import (
    american_to_implied_probability,
    remove_two_way_vig,
    score_prop_board,
)


def test_american_odds_conversion() -> None:
    assert round(american_to_implied_probability(-110), 4) == 0.5238
    assert round(american_to_implied_probability(150), 4) == 0.4
    over, under = remove_two_way_vig(-110, -110)
    assert round(over, 6) == 0.5
    assert round(under, 6) == 0.5


def test_score_prop_board() -> None:
    predictions = pd.DataFrame(
        {
            "player_id": ["p1"],
            "player_name": ["Player One"],
            "game_id": ["g1"],
            "recent_team": ["A"],
            "fantasy_points_ppr_q10": [10.0],
            "fantasy_points_ppr_q50": [20.0],
            "fantasy_points_ppr_q90": [30.0],
        }
    )
    props = pd.DataFrame(
        {
            "player_id": ["p1"],
            "target": ["fantasy_points_ppr"],
            "line": [15.0],
            "over_odds": [-110],
            "under_odds": [-110],
        }
    )
    scored = score_prop_board(predictions, props)
    assert len(scored) == 1
    assert scored.loc[0, "model_over_probability"] > 0.5
    assert scored.loc[0, "preferred_side"] == "over"
