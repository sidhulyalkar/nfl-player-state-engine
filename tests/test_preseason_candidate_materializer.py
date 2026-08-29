from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from player_state_engine.product.preseason_candidate import build_preseason_product_frame


def _predictions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": "00-0000001",
                "player_name": "Player One",
                "position": "QB",
                "recent_team": "BUF",
                "fantasy_points_ppr_q10": 210.0,
                "fantasy_points_ppr_q50": 280.0,
                "fantasy_points_ppr_q90": 350.0,
                "passing_yards_q10": 3000.0,
                "passing_yards_q50": 4000.0,
                "passing_yards_q90": 4800.0,
            }
        ]
    )


def test_product_candidate_is_explicitly_nonproduction_and_pending_uncertainty() -> None:
    frame = build_preseason_product_frame(
        _predictions(),
        source_cutoff_utc=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )

    row = frame.iloc[0]
    assert row["artifact_authority"] == "challenger"
    assert bool(row["activation_eligible"]) is False
    assert row["decision_quantile_policy"] == "pending_uncertainty_qualification"
    assert row["uncertainty_authority"] == "pending_separate_production_qualification"
    assert row["season_points_q50"] == 280.0
    assert row["season"] == 2026


def test_duplicate_identity_fails_closed() -> None:
    duplicated = pd.concat([_predictions(), _predictions()], ignore_index=True)
    with pytest.raises(ValueError, match="unique non-empty"):
        build_preseason_product_frame(
            duplicated,
            source_cutoff_utc=datetime(2026, 8, 29, tzinfo=UTC),
        )


def test_nonmonotonic_quantiles_fail_closed() -> None:
    predictions = _predictions()
    predictions.loc[0, "fantasy_points_ppr_q10"] = 300.0
    with pytest.raises(ValueError, match="non-monotonic"):
        build_preseason_product_frame(
            predictions,
            source_cutoff_utc=datetime(2026, 8, 29, tzinfo=UTC),
        )
