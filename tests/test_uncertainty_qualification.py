from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from player_state_engine.evaluation.uncertainty_qualification import (
    ConformalQualificationGate,
    qualify_conformal_predictions,
)

TARGET = "league_fantasy_points"


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    for index in range(40):
        actual = float(index)
        rows.append(
            {
                "season": 2025,
                "player_id": f"p{index}",
                "position": "WR" if index % 2 else "RB",
                "actual": actual,
                f"{TARGET}_q10": actual - 4.0,
                f"{TARGET}_q50": actual + 1.0,
                f"{TARGET}_q90": actual + 4.0,
            }
        )
    raw = pd.DataFrame(rows)
    calibrated = raw.copy()
    calibrated[f"{TARGET}_q50"] = calibrated["actual"]
    calibrated["conformal_applied"] = 1
    return raw, calibrated


def test_uncertainty_qualification_pairs_rows_and_reports_metrics() -> None:
    raw, calibrated = _frames()
    policy = ConformalQualificationGate(
        nominal_interval_coverage=1.0,
        overall_coverage_tolerance=0.01,
        min_position_coverage=0.99,
        max_position_coverage=1.0,
        max_overall_pinball_regression_pct=100.0,
        max_position_pinball_regression_pct=100.0,
        max_q50_abs_bias_worsening_points=2.0,
    )

    decision, overall, positions = qualify_conformal_predictions(
        raw,
        calibrated,
        target=TARGET,
        policy=policy,
    )

    assert decision.approved is True
    assert decision.blockers == ()
    assert decision.metrics["evaluable_rows"] == 40.0
    assert set(overall["method"]) == {"raw", "conformal"}
    assert set(positions["group"]) == {"RB", "WR"}


def test_default_gate_rejects_gross_overcoverage() -> None:
    raw, calibrated = _frames()
    decision, _, _ = qualify_conformal_predictions(raw, calibrated, target=TARGET)

    assert decision.approved is False
    assert "OVERALL_INTERVAL_COVERAGE_OUTSIDE_TOLERANCE" in decision.blockers
    assert "POSITION_INTERVAL_COVERAGE:RB" in decision.blockers
    assert "POSITION_INTERVAL_COVERAGE:WR" in decision.blockers


def test_uncertainty_qualification_requires_applied_rows() -> None:
    raw, calibrated = _frames()
    calibrated["conformal_applied"] = np.nan
    with pytest.raises(ValueError, match="No conformal-evaluable seasons remain"):
        qualify_conformal_predictions(raw, calibrated, target=TARGET)
