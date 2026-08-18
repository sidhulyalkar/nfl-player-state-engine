from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.game_intelligence.transition_benchmark import _aggregate_isolated


def test_isolated_metrics_use_their_own_evidence_denominators() -> None:
    weekly = pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 1,
                "transition_rows": 1000.0,
                "transition_start_rows": 900.0,
                "transition_seconds_rows": 800.0,
                "field_goal_rows": 2.0,
                "transition_start_yardline_mae": 10.0,
                "transition_seconds_mae": 5.0,
                "field_goal_log_loss": 0.1,
                "permuted_field_goal_log_loss": 0.2,
            },
            {
                "season": 2025,
                "week": 2,
                "transition_rows": 10.0,
                "transition_start_rows": 10.0,
                "transition_seconds_rows": 10.0,
                "field_goal_rows": 18.0,
                "transition_start_yardline_mae": 20.0,
                "transition_seconds_mae": 15.0,
                "field_goal_log_loss": 0.9,
                "permuted_field_goal_log_loss": 0.8,
            },
        ]
    )
    aggregate = _aggregate_isolated(weekly)

    expected_start = (10.0 * 900.0 + 20.0 * 10.0) / 910.0
    expected_seconds = (5.0 * 800.0 + 15.0 * 10.0) / 810.0
    expected_fg = (0.1 * 2.0 + 0.9 * 18.0) / 20.0
    expected_permuted_fg = (0.2 * 2.0 + 0.8 * 18.0) / 20.0

    assert np.isclose(aggregate["transition_start_yardline_mae"], expected_start)
    assert np.isclose(aggregate["transition_seconds_mae"], expected_seconds)
    assert np.isclose(aggregate["field_goal_log_loss"], expected_fg)
    assert np.isclose(aggregate["permuted_field_goal_log_loss"], expected_permuted_fg)
    assert aggregate["transition_rows"] == 1010.0
    assert aggregate["field_goal_rows"] == 20.0
