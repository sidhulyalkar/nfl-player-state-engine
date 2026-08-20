from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.fantasy.draft_evaluation import (
    compare_survival_models_paired,
    evaluate_survival_predictions,
    grouped_survival_report,
)


def _history(seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    for draft_id in range(40):
        for index in range(20):
            true_probability = float(np.clip(0.08 + 0.045 * index, 0.05, 0.95))
            outcome = float(rng.random() < true_probability)
            rows.append(
                {
                    "draft_id": f"D{draft_id}",
                    "position": "QB" if index % 4 == 0 else "WR",
                    "league_type": "2QB" if draft_id % 2 == 0 else "1QB",
                    "draft_round": 1 + index // 8,
                    "survived_to_next_pick": outcome,
                    "good_probability": true_probability,
                    "bad_probability": float(np.clip(0.85 - 0.02 * index, 0.05, 0.95)),
                }
            )
    return pd.DataFrame(rows)


def test_survival_evaluation_rewards_calibrated_probability_forecasts() -> None:
    history = _history()
    good = evaluate_survival_predictions(
        history, model="good", prediction_column="good_probability"
    )
    bad = evaluate_survival_predictions(
        history, model="bad", prediction_column="bad_probability"
    )
    assert good.rows == len(history)
    assert good.brier_score < bad.brier_score
    assert good.log_loss < bad.log_loss
    assert 0.0 <= good.calibration_error <= 1.0


def test_grouped_report_exposes_position_and_league_type() -> None:
    report = grouped_survival_report(
        _history(),
        model="good",
        prediction_column="good_probability",
        minimum_rows=20,
    )
    assert ((report["group"] == "overall") & (report["value"] == "all")).any()
    assert "position" in set(report["group"])
    assert "league_type" in set(report["group"])


def test_paired_block_bootstrap_detects_better_challenger() -> None:
    history = _history()
    comparison = compare_survival_models_paired(
        history,
        challenger_column="good_probability",
        baseline_column="bad_probability",
        challenger_name="room",
        baseline_name="normal_adp",
        bootstrap_samples=1000,
        seed=8,
    )
    assert comparison.brier_delta < 0.0
    assert comparison.probability_better > 0.95
    assert comparison.supports_promotion
