from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.player_state.benchmark import (
    compare_forecasts,
    evaluate_forecast,
    grouped_forecast_scorecards,
)


def _archive(seed: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    for season in (2023, 2024, 2025):
        for week in range(1, 11):
            for index in range(12):
                mean = 8.0 + 0.7 * index + 0.2 * week
                actual = float(rng.normal(mean, 2.0))
                rows.append(
                    {
                        "season": season,
                        "week": week,
                        "player_id": f"P{index}",
                        "position": "WR" if index % 2 else "RB",
                        "target": "fantasy_points",
                        "actual": actual,
                        "direct_q10": mean - 2.8,
                        "direct_q50": mean,
                        "direct_q90": mean + 2.8,
                        "graph_q10": mean - 4.5,
                        "graph_q50": mean + 1.8,
                        "graph_q90": mean + 6.0,
                    }
                )
    return pd.DataFrame(rows)


def test_scorecard_rewards_better_calibrated_sharper_forecast() -> None:
    archive = _archive()
    direct = evaluate_forecast(archive, model="direct")
    graph = evaluate_forecast(archive, model="graph")
    assert direct.rows == len(archive)
    assert direct.weighted_interval_score < graph.weighted_interval_score
    assert direct.median_mae < graph.median_mae
    assert 0.0 <= direct.interval_coverage <= 1.0


def test_forecast_comparison_uses_paired_season_week_blocks() -> None:
    comparison = compare_forecasts(
        _archive(),
        candidate="direct",
        reference="graph",
        bootstrap_samples=800,
        seed=3,
    )
    assert comparison.wis_effect.effect < 0.0
    assert comparison.wis_effect.probability_improves > 0.95
    assert comparison.wis_effect.blocks == 30
    assert comparison.season_consistency == 1.0
    assert comparison.position_consistency == 1.0


def test_grouped_scorecards_expose_season_and_position() -> None:
    report = grouped_forecast_scorecards(
        _archive(), models=("direct", "graph"), minimum_rows=20
    )
    assert set(report["model"]) == {"direct", "graph"}
    assert "season" in set(report["group"])
    assert "position" in set(report["group"])
