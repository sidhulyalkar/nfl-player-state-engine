import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import score_fantasy_stats


def test_league_scoring_supports_ppr_and_te_premium() -> None:
    frame = pd.DataFrame(
        {
            "position": ["WR", "TE"],
            "receptions": [5, 5],
            "receiving_yards": [60, 60],
            "receiving_tds": [1, 1],
        }
    )
    config = LeagueConfig(scoring="ppr", tight_end_premium=0.5)
    scores = score_fantasy_stats(frame, config)
    assert scores.iloc[1] == scores.iloc[0] + 2.5
