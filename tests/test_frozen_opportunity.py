from __future__ import annotations

import pandas as pd

from player_state_engine.evaluation.frozen_opportunity import build_frozen_opportunity_features


def test_frozen_features_are_shifted() -> None:
    rows = []
    for week, targets in [(1, 2), (2, 8), (3, 4)]:
        rows.append(
            {
                "season": 2024,
                "week": week,
                "game_id": f"g{week}",
                "player_id": "p1",
                "player_name": "P",
                "recent_team": "A",
                "opponent_team": "B",
                "position": "WR",
                "fantasy_points_ppr_q10": 1,
                "fantasy_points_ppr_q50": 5,
                "fantasy_points_ppr_q90": 12,
                "actual_fantasy_points_ppr": targets + 3,
                "actual_carries": 0,
                "actual_targets": targets,
                "actual_receptions": targets / 2,
                "actual_receiving_yards": targets * 8,
                "actual_rushing_yards": 0,
                "actual_passing_yards": 0,
            }
        )
    features = build_frozen_opportunity_features(pd.DataFrame(rows))
    assert pd.isna(features.loc[0, "history_actual_targets_lag1"])
    assert features.loc[1, "history_actual_targets_lag1"] == 2
    assert features.loc[2, "history_actual_targets_lag1"] == 8
