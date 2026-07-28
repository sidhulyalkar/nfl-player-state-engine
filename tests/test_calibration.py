from __future__ import annotations

import pandas as pd

from player_state_engine.evaluation.calibration import (
    interval_calibration_table,
    quantile_calibration_table,
)


def test_calibration_tables_report_nominal_error() -> None:
    frame = pd.DataFrame(
        {
            "method": ["m"] * 10,
            "position": ["WR"] * 10,
            "actual": list(range(10)),
            "yards_q10": [0.0] * 10,
            "yards_q50": [4.5] * 10,
            "yards_q90": [9.0] * 10,
        }
    )
    quantile = quantile_calibration_table(frame, "yards")
    median = quantile.loc[quantile["quantile"] == 0.5].iloc[0]
    assert median["empirical_rate"] == 0.5
    interval = interval_calibration_table(frame, "yards")
    assert interval.iloc[0]["empirical_coverage"] == 1.0
