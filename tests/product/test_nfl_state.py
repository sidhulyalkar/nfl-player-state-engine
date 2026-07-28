import pandas as pd

from player_state_engine.product.nfl_state import build_nfl_state


def test_build_nfl_state():
    schedules = pd.DataFrame(
        [
            {
                "season": 2026,
                "week": 1,
                "game_type": "REG",
                "home_team": "SF",
                "away_team": "SEA",
                "home_score": 24,
                "away_score": 17,
            },
            {
                "season": 2026,
                "week": 2,
                "game_type": "REG",
                "home_team": "LAR",
                "away_team": "SF",
                "home_score": 20,
                "away_score": 20,
            },
        ]
    )
    state = build_nfl_state(schedules, 2026, 2)
    sf = next(team for team in state.teams if team.team == "SF")
    assert sf.wins == 1 and sf.ties == 1
    assert sf.streak == "T1"
