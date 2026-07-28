from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.models.conformal import apply_earlier_season_conformal


def test_conformal_uses_only_earlier_seasons_and_is_monotonic() -> None:
    rows = []
    rng = np.random.default_rng(4)
    for season, bias in [(2021, 6.0), (2022, 7.0), (2023, 8.0)]:
        for i in range(120):
            actual = 250 + rng.normal(0, 40)
            rows.append(
                {
                    "season": season,
                    "week": 1 + i % 18,
                    "position": "QB",
                    "method": "quantile_engine",
                    "actual": actual,
                    "passing_yards_q10": actual - 35 - bias,
                    "passing_yards_q50": actual - bias,
                    "passing_yards_q90": actual + 35 - bias,
                }
            )
    calibrated, diagnostics = apply_earlier_season_conformal(pd.DataFrame(rows), "passing_yards")
    first = calibrated.loc[calibrated["season"] == 2021]
    later = calibrated.loc[calibrated["season"] == 2023]
    assert first["conformal_applied"].eq(0).all()
    assert later["conformal_fitted_through_season"].eq(2022).all()
    assert (later["passing_yards_q10"] <= later["passing_yards_q50"]).all()
    assert (later["passing_yards_q50"] <= later["passing_yards_q90"]).all()
    assert not diagnostics.empty
