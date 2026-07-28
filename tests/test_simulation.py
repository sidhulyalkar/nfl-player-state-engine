from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.simulation.game import build_correlation_matrix, simulate_slate


def _predictions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": [2026] * 4,
            "week": [1] * 4,
            "game_id": ["game"] * 4,
            "player_id": ["a", "b", "c", "d"],
            "player_name": ["QB A", "WR A", "QB B", "WR B"],
            "recent_team": ["A", "A", "B", "B"],
            "opponent_team": ["B", "B", "A", "A"],
            "position": ["QB", "WR", "QB", "WR"],
            "fantasy_points_ppr_q10": [10, 4, 9, 3],
            "fantasy_points_ppr_q50": [18, 12, 17, 11],
            "fantasy_points_ppr_q90": [28, 23, 27, 21],
        }
    )


def test_correlation_matrix_is_psd() -> None:
    matrix = build_correlation_matrix(_predictions())
    assert np.linalg.eigvalsh(matrix).min() > 0
    assert matrix[0, 1] > matrix[0, 2]


def test_simulation_outputs_summaries() -> None:
    result = simulate_slate(_predictions(), draws=500, seed=7)
    assert result.draws.shape == (500, 4)
    assert len(result.player_summary) == 4
    assert len(result.team_summary) == 2
    assert len(result.game_summary) == 1
    assert (result.player_summary["p10"] <= result.player_summary["median"]).all()
