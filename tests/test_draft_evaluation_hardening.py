from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.draft_evaluation import compare_survival_models_paired


def test_draft_bootstrap_preserves_row_weighted_estimand_with_unequal_draft_sizes() -> None:
    rows: list[dict[str, object]] = []
    for index in range(9):
        rows.append(
            {
                "draft_id": "large",
                "row": index,
                "survived_to_next_pick": 0.0,
                "challenger": 0.0,
                "baseline": 1.0,
            }
        )
    rows.append(
        {
            "draft_id": "small",
            "row": 0,
            "survived_to_next_pick": 0.0,
            "challenger": 1.0,
            "baseline": 0.0,
        }
    )
    comparison = compare_survival_models_paired(
        pd.DataFrame(rows),
        challenger_column="challenger",
        baseline_column="baseline",
        bootstrap_samples=4000,
        seed=11,
    )
    assert comparison.brier_delta == -0.8
    # With sum/count resampling, a mixed large+small draft draw remains negative (-0.8).
    # Equal-weighting draft means would incorrectly turn that same draw into exactly zero.
    assert comparison.probability_better > 0.60
