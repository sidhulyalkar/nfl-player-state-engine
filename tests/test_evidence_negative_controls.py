from __future__ import annotations

import pandas as pd

from player_state_engine.evaluation.evidence_factory import canonicalize_predictions
from player_state_engine.evaluation.negative_controls import (
    evaluate_identity_permutation_control,
    identity_permutation_control,
)


def _perfect_predictions() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for season in (2023, 2024):
        for week in range(1, 9):
            actual = float(week * 3 + (season - 2023) * 2)
            rows.append(
                {
                    "player_id": f"p{week}",
                    "season": season,
                    "week": week,
                    "position": "WR",
                    "method": "challenger",
                    "actual": actual,
                    "fantasy_points_ppr_q10": actual - 2.0,
                    "fantasy_points_ppr_q50": actual,
                    "fantasy_points_ppr_q90": actual + 2.0,
                }
            )
    return canonicalize_predictions(pd.DataFrame(rows), target="fantasy_points_ppr")


def test_identity_permutation_preserves_forecast_marginals_but_breaks_player_mapping() -> None:
    real = _perfect_predictions()

    control, diagnostics = identity_permutation_control(
        real,
        method="challenger",
        target="fantasy_points_ppr",
        seed=9,
    )

    assert diagnostics == {"groups": 2, "singleton_groups": 0}
    assert set(control["method"]) == {"challenger__identity_permutation_control"}
    assert sorted(control["q50"].tolist()) == sorted(real["q50"].tolist())
    assert not control["q50"].equals(real["q50"])
    assert control["forecast_id"].is_unique


def test_real_forecast_clears_identity_negative_control_only_with_positive_paired_ci() -> None:
    real = _perfect_predictions()
    control, diagnostics = identity_permutation_control(
        real,
        method="challenger",
        target="fantasy_points_ppr",
        seed=19,
    )

    result = evaluate_identity_permutation_control(
        real,
        control,
        method="challenger",
        target="fantasy_points_ppr",
        bootstrap_samples=800,
        seed=31,
        **diagnostics,
    )

    assert result.rows == 16
    assert result.control_mean_pinball > result.real_mean_pinball
    assert result.effect_control_minus_real > 0.0
    assert result.ci_low > 0.0
    assert result.passed is True


def test_identity_control_is_deterministic_for_fixed_seed() -> None:
    real = _perfect_predictions()

    first, first_diagnostics = identity_permutation_control(
        real,
        method="challenger",
        target="fantasy_points_ppr",
        seed=123,
    )
    second, second_diagnostics = identity_permutation_control(
        real,
        method="challenger",
        target="fantasy_points_ppr",
        seed=123,
    )

    pd.testing.assert_frame_equal(first, second)
    assert first_diagnostics == second_diagnostics
