from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.evaluation.ablations import (
    build_ablation_feature_sets,
    make_shifted_time_control,
    make_shuffled_player_control,
)
from player_state_engine.models.intelligence_residual import IntelligenceResidualAdjuster


def test_ablation_sets_and_controls_are_explicit() -> None:
    frame = pd.DataFrame(
        {
            "season": [2024] * 4,
            "week": [1] * 4,
            "position": ["RB"] * 4,
            "player_id": ["a", "b", "c", "d"],
            "base": [1, 2, 3, 4],
            "availability_expected_active": [0.1, 0.2, 0.3, 0.4],
            "opportunity_snap_share_roll3_mean": [0.4, 0.5, 0.6, 0.7],
            "news_starter_role": [0, 1, 0, 1],
            "persona_training_focus": [0.2, 0.3, 0.4, 0.5],
        }
    )
    sets = build_ablation_feature_sets(["base"], frame)
    assert "availability_expected_active" in sets["official_availability_only"]
    assert "news_starter_role" in sets["news_only"]
    shuffled = make_shuffled_player_control(frame, seed=2)
    assert sorted(shuffled["persona_training_focus"]) == sorted(frame["persona_training_focus"])
    shifted = make_shifted_time_control(pd.concat([frame, frame.assign(week=2)], ignore_index=True))
    assert shifted.shape == (8, frame.shape[1])


def test_residual_adjuster_caps_soft_intelligence_effect() -> None:
    rng = np.random.default_rng(9)
    n = 120
    intel = pd.DataFrame({"persona_training_focus": rng.uniform(0, 1, n)})
    baseline = pd.DataFrame(
        {
            "fantasy_points_ppr_q10": np.full(n, 5.0),
            "fantasy_points_ppr_q50": np.full(n, 10.0),
            "fantasy_points_ppr_q90": np.full(n, 15.0),
        }
    )
    baseline["actual"] = 10 + 2 * intel["persona_training_focus"] + rng.normal(0, 1, n)
    model = IntelligenceResidualAdjuster().fit(
        intel,
        baseline,
        "fantasy_points_ppr",
        ["persona_training_focus"],
    )
    adjusted = model.transform(intel, baseline)
    assert adjusted["intelligence_center_shift"].abs().max() <= 1.25 + 1e-9
    assert adjusted["intelligence_width_scale"].between(0.85, 1.15).all()
