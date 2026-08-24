from __future__ import annotations

import pandas as pd
import pytest

from player_state_engine.evaluation.evidence_factory import (
    build_evidence_bundle,
    canonicalize_predictions,
    compare_methods,
)
from player_state_engine.state_graph.experiments import EvidenceTier


def _raw_predictions(method: str, *, offset: float = 0.0) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    actuals = [10.0, 15.0, 20.0, 25.0, 12.0, 18.0, 22.0, 28.0]
    for index, actual in enumerate(actuals):
        season = 2023 if index < 4 else 2024
        week = index % 4 + 1
        q50 = actual + offset
        rows.append(
            {
                "player_id": f"p{index % 2}",
                "season": season,
                "week": week,
                "position": "WR" if index % 2 == 0 else "RB",
                "method": method,
                "actual": actual,
                "fantasy_points_ppr_q10": q50 - 4.0,
                "fantasy_points_ppr_q50": q50,
                "fantasy_points_ppr_q90": q50 + 4.0,
            }
        )
    return pd.DataFrame(rows)


def test_canonicalize_predictions_preserves_point_in_time_identity() -> None:
    raw = _raw_predictions("quantile_engine")
    raw["prediction_cutoff"] = "2024-09-01T16:00:00Z"

    result = canonicalize_predictions(raw, target="fantasy_points_ppr")

    assert len(result) == len(raw)
    assert set(result["method"]) == {"quantile_engine"}
    assert result["forecast_id"].is_unique
    assert result["valid_prediction"].all()
    assert not result["crossed_quantiles"].any()
    assert set(result["prediction_cutoff"]) == {"2024-09-01T16:00:00Z"}


def test_canonicalize_predictions_rejects_duplicate_player_week_method() -> None:
    raw = _raw_predictions("quantile_engine")
    raw = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="Duplicate canonical prediction rows"):
        canonicalize_predictions(raw, target="fantasy_points_ppr")


def test_paired_comparison_uses_identical_player_weeks_and_remains_fail_closed() -> None:
    champion = canonicalize_predictions(
        _raw_predictions("quantile_engine", offset=2.0), target="fantasy_points_ppr"
    )
    challenger = canonicalize_predictions(
        _raw_predictions("player_state_graph", offset=0.0), target="fantasy_points_ppr"
    )
    combined = pd.concat([champion, challenger], ignore_index=True)

    comparison, record = compare_methods(
        combined,
        target="fantasy_points_ppr",
        champion_method="quantile_engine",
        challenger_method="player_state_graph",
        bootstrap_samples=400,
        seed=7,
    )

    assert comparison["paired_rows"] == 8
    assert comparison["paired_seasons"] == 2
    assert comparison["pinball_effect_champion_minus_challenger"] > 0.0
    assert record.evidence_tier == EvidenceTier.MULTI_SEASON_ISOLATED
    assert record.promoted is False
    assert "evidence_tier<3" in record.blockers
    assert "negative_control_failed" in record.blockers


def test_paired_comparison_rejects_disagreeing_realized_outcomes() -> None:
    champion = canonicalize_predictions(_raw_predictions("quantile_engine"), target="fantasy_points_ppr")
    challenger_raw = _raw_predictions("player_state_graph")
    challenger_raw.loc[0, "actual"] = 999.0
    challenger = canonicalize_predictions(challenger_raw, target="fantasy_points_ppr")

    with pytest.raises(ValueError, match="disagree on the realized outcome"):
        compare_methods(
            pd.concat([champion, challenger], ignore_index=True),
            target="fantasy_points_ppr",
            champion_method="quantile_engine",
            challenger_method="player_state_graph",
        )


def test_evidence_bundle_compares_all_available_baselines_to_champion() -> None:
    champion = canonicalize_predictions(
        _raw_predictions("quantile_engine", offset=0.5), target="fantasy_points_ppr"
    )
    rolling = canonicalize_predictions(
        _raw_predictions("rolling_5", offset=1.5), target="fantasy_points_ppr"
    )
    prior = canonicalize_predictions(
        _raw_predictions("position_prior", offset=2.5), target="fantasy_points_ppr"
    )

    bundle = build_evidence_bundle(
        [champion, rolling, prior],
        champion_method="quantile_engine",
        bootstrap_samples=300,
        seed=11,
    )

    assert set(bundle.method_summary["method"]) == {
        "quantile_engine",
        "rolling_5",
        "position_prior",
    }
    assert set(bundle.paired_comparisons["challenger"]) == {"rolling_5", "position_prior"}
    assert set(bundle.slice_metrics["scope"]) >= {
        "overall",
        "season",
        "position",
        "position_season",
        "week",
    }
    assert len(bundle.experiment_ledger) == 2


def test_interval_undercoverage_is_an_explicit_promotion_blocker() -> None:
    champion = canonicalize_predictions(_raw_predictions("quantile_engine"), target="fantasy_points_ppr")
    challenger_raw = _raw_predictions("narrow_challenger")
    challenger_raw["fantasy_points_ppr_q10"] = challenger_raw["actual"] + 1.0
    challenger_raw["fantasy_points_ppr_q50"] = challenger_raw["actual"] + 1.5
    challenger_raw["fantasy_points_ppr_q90"] = challenger_raw["actual"] + 2.0
    challenger = canonicalize_predictions(challenger_raw, target="fantasy_points_ppr")

    _comparison, record = compare_methods(
        pd.concat([champion, challenger], ignore_index=True),
        target="fantasy_points_ppr",
        champion_method="quantile_engine",
        challenger_method="narrow_challenger",
        bootstrap_samples=300,
    )

    assert "challenger_interval_coverage_outside_tolerance" in record.blockers
    assert record.promoted is False
