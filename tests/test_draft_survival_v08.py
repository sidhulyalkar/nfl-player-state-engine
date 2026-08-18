from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.draft_survival import apply_empirical_survival, train_survival_model
from player_state_engine.fantasy.league import LeagueConfig


def _observations() -> pd.DataFrame:
    rows = []
    for draft in range(10):
        for index in range(40):
            survives = int(index % 2 == 0)
            rows.append(
                {
                    "draft_id": f"d{draft}",
                    "current_pick": 20 + index % 4,
                    "next_pick": 30 + index % 4,
                    "market_adp": 30.0,
                    "market_adp_sd": 8.0,
                    "teams": 10,
                    "position": "WR" if survives else "QB",
                    "platform": "sleeper",
                    "scoring": "ppr",
                    "qb_slots_per_team": 2,
                    "superflex_slots_per_team": 0,
                    "starter_slots_per_team": 10,
                    "recent_position_run": 1,
                    "survived_to_next_pick": survives,
                }
            )
    return pd.DataFrame(rows)


def test_empirical_survival_must_beat_fallback_before_promotion() -> None:
    artifact = train_survival_model(_observations(), min_rows=100, min_drafts=5)
    assert artifact.promoted
    assert float(artifact.metrics["brier"]) < float(artifact.metrics["fallback_brier"])


def test_unpromoted_artifact_falls_back_without_rewriting_live_score() -> None:
    artifact = train_survival_model(
        _observations(), min_rows=100, min_drafts=5, min_brier_improvement=1.0
    )
    assert not artifact.promoted
    board = pd.DataFrame(
        [
            {
                "player_id": "p1",
                "player_name": "Player One",
                "position": "QB",
                "market_adp": 28.0,
                "market_adp_sd": 8.0,
                "survival_to_next_pick": 0.40,
                "live_draft_score": 80.0,
                "reach_rounds": 0.5,
            }
        ]
    )
    config = LeagueConfig(teams=10, roster_slots={"QB": 2, "RB": 2, "WR": 2, "TE": 1})
    result = apply_empirical_survival(
        board, artifact, config, current_pick=20, next_pick=31, platform="sleeper"
    )
    assert float(result.iloc[0].live_draft_score) == 80.0
    assert float(result.iloc[0].survival_to_next_pick) == 0.40
    assert result.iloc[0].survival_model_source == "normal_adp_fallback_unpromoted"
