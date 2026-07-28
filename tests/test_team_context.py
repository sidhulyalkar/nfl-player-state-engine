import pandas as pd

from player_state_engine.features.team_context import (
    build_team_play_structure,
    score_player_scheme_fit,
)


def test_team_context_is_lagged_and_scheme_fit_is_bounded() -> None:
    rows = []
    for week in [1, 2, 3, 4, 5]:
        for play in range(12):
            rows.append(
                {
                    "season": 2024,
                    "week": week,
                    "posteam": "AAA",
                    "pass_attempt": int(play < 8),
                    "rush_attempt": int(play >= 8),
                    "score_differential": 0,
                    "qtr": 2,
                    "yardline_100": 50,
                    "shotgun": 1,
                    "no_huddle": 0,
                    "receiver_player_id": f"r{play % 2}" if play < 8 else None,
                    "rusher_player_id": f"b{play % 2}" if play >= 8 else None,
                }
            )
    context = build_team_play_structure(pd.DataFrame(rows))
    assert context.loc[context["week"].eq(1), "team_pass_rate_lag1"].isna().all()
    players = pd.DataFrame(
        {
            "season": [2024, 2024, 2024],
            "week": [5, 5, 5],
            "recent_team": ["AAA", "AAA", "AAA"],
            "position": ["QB", "RB", "WR"],
        }
    )
    fitted = score_player_scheme_fit(players, context)
    assert fitted["scheme_fit_score"].between(0, 1).all()
    assert "role_system_integration_score" in fitted
