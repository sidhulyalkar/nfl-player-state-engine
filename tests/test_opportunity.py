from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.config import ModelConfig
from player_state_engine.features.opportunity import derive_opportunity_targets
from player_state_engine.models.opportunity import OpportunityHeadBundle


def test_derive_opportunity_targets_creates_causal_labels() -> None:
    frame = pd.DataFrame(
        {
            "season": [2024, 2024],
            "week": [1, 1],
            "recent_team": ["A", "A"],
            "passing_attempts": [30, 0],
            "carries": [2, 18],
            "targets": [0, 5],
            "receptions": [0, 4],
            "snap_count": [60, 45],
            "route_count": [0, 20],
            "passing_tds": [2, 0],
            "rushing_tds": [0, 1],
            "receiving_tds": [0, 0],
        }
    )
    result = derive_opportunity_targets(frame)
    assert result["opportunity_team_plays"].eq(50).all()
    assert np.isclose(result.loc[1, "opportunity_carry_share"], 0.9)
    assert np.isclose(result.loc[1, "opportunity_target_share"], 1.0)
    assert result["opportunity_active"].eq(1).all()


def test_opportunity_head_bundle_runs_temporal_ladder() -> None:
    rng = np.random.default_rng(8)
    rows = []
    for season in (2021, 2022, 2023):
        for i in range(36):
            x = rng.normal()
            active = float(i % 6 != 0)
            snap = np.clip(0.55 + 0.15 * x + rng.normal(0, 0.05), 0, 1) * active
            targets = max(0.0, 5 + 2 * x + rng.normal()) * active
            receptions = max(0.0, 0.65 * targets + rng.normal(0, 0.5))
            fantasy = max(0.0, receptions * 2.0 + rng.normal())
            rows.append(
                {
                    "season": season,
                    "week": 1 + i % 18,
                    "position": "RB",
                    "player_id": f"p{i}",
                    "recent_team": "A",
                    "x": x,
                    "opportunity_active": active,
                    "opportunity_snap_share": snap,
                    "targets": targets,
                    "receptions": receptions,
                    "fantasy_points_ppr": fantasy,
                }
            )
    frame = pd.DataFrame(rows)
    config = ModelConfig(max_iter=12, min_samples_leaf=5, max_leaf_nodes=7)
    bundle = OpportunityHeadBundle(config).fit(frame, ["x", "position"])
    predicted = bundle.predict(frame.tail(12))
    assert predicted["opportunity_active_probability"].between(0, 1).all()
    assert "opportunity_snap_share_q50" in predicted
    assert "targets_q50" in predicted
    assert "receptions_q50" in predicted
    assert "fantasy_points_ppr_q50" in predicted
