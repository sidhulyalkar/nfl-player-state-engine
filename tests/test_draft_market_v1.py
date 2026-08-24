from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from player_state_engine.fantasy.draft_market import (
    chronological_room_holdout,
    train_chronological_survival_model,
)
from scripts.build_draft_survival_observations import build_observations


def _market_observations(*, verified: bool = True) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    start = datetime(2024, 7, 1, tzinfo=UTC)
    for draft_index in range(12):
        draft_time = start + timedelta(days=7 * draft_index)
        for row_index in range(40):
            run = row_index % 4
            survives = int(run >= 2)
            rows.append(
                {
                    "draft_id": f"draft-{draft_index:02d}",
                    "draft_started_at": draft_time.isoformat(),
                    "point_in_time_market_verified": verified,
                    "current_pick": 20 + row_index % 3,
                    "next_pick": 31 + row_index % 3,
                    "market_adp": 30.0,
                    "market_adp_sd": 8.0,
                    "teams": 10,
                    "position": "WR",
                    "platform": "sleeper",
                    "scoring": "ppr",
                    "qb_slots_per_team": 2,
                    "superflex_slots_per_team": 0,
                    "starter_slots_per_team": 10,
                    "recent_position_run": run,
                    "survived_to_next_pick": survives,
                }
            )
    return pd.DataFrame(rows)


def _format_regression_observations() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    start = datetime(2024, 5, 1, tzinfo=UTC)
    for draft_index in range(20):
        draft_time = start + timedelta(days=5 * draft_index)
        format_b = draft_index in {4, 9, 14, 19}
        for row_index in range(40):
            run = row_index % 4
            survives = int(run >= 2)
            if draft_index == 19:
                survives = 1 - survives
            rows.append(
                {
                    "draft_id": f"format-shift-{draft_index:02d}",
                    "draft_started_at": draft_time.isoformat(),
                    "point_in_time_market_verified": True,
                    "current_pick": 20 + row_index % 3,
                    "next_pick": 31 + row_index % 3,
                    "market_adp": 30.0,
                    "market_adp_sd": 8.0,
                    "teams": 10,
                    "position": "WR",
                    "platform": "sleeper",
                    "scoring": "half_ppr" if format_b else "ppr",
                    "qb_slots_per_team": 2,
                    "superflex_slots_per_team": 0,
                    "starter_slots_per_team": 10,
                    "recent_position_run": run,
                    "survived_to_next_pick": survives,
                }
            )
    return pd.DataFrame(rows)


def _room_fragility_observations() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    start = datetime(2024, 4, 1, tzinfo=UTC)
    for draft_index in range(20):
        draft_time = start + timedelta(days=5 * draft_index)
        if draft_index < 15:
            room_rows = 40
            reverse = False
        elif draft_index in {15, 16}:
            room_rows = 100
            reverse = False
        else:
            room_rows = 10
            reverse = True
        for row_index in range(room_rows):
            run = row_index % 4
            survives = int(run >= 2)
            if reverse:
                survives = 1 - survives
            rows.append(
                {
                    "draft_id": f"fragile-{draft_index:02d}",
                    "draft_started_at": draft_time.isoformat(),
                    "point_in_time_market_verified": True,
                    "current_pick": 20 + row_index % 3,
                    "next_pick": 31 + row_index % 3,
                    "market_adp": 30.0,
                    "market_adp_sd": 8.0,
                    "teams": 10,
                    "position": "WR",
                    "platform": "sleeper",
                    "scoring": "ppr",
                    "qb_slots_per_team": 2,
                    "superflex_slots_per_team": 0,
                    "starter_slots_per_team": 10,
                    "recent_position_run": run,
                    "survived_to_next_pick": survives,
                }
            )
    return pd.DataFrame(rows)


def test_chronological_holdout_is_strict_and_order_invariant() -> None:
    observations = _market_observations()
    first = chronological_room_holdout(observations, test_fraction=0.25, min_holdout_drafts=2)
    shuffled = observations.sample(frac=1.0, random_state=17).reset_index(drop=True)
    second = chronological_room_holdout(shuffled, test_fraction=0.25, min_holdout_drafts=2)

    assert first.split_kind == "timestamp"
    assert set(first.train_drafts) == set(second.train_drafts)
    assert set(first.test_drafts) == set(second.test_drafts)
    assert set(first.train_drafts).isdisjoint(first.test_drafts)
    assert max(first.train_drafts) < min(first.test_drafts)


def test_season_only_history_requires_forward_season_transfer() -> None:
    observations = _market_observations().drop(columns=["draft_started_at"])
    observations["season"] = 2025

    with pytest.raises(ValueError, match="at least two seasons"):
        chronological_room_holdout(observations)


def test_verified_chronological_model_can_clear_both_adp_baselines() -> None:
    result = train_chronological_survival_model(
        _market_observations(),
        min_rows=200,
        min_drafts=8,
        test_fraction=0.25,
        min_holdout_drafts=2,
        min_brier_improvement=0.001,
        max_ece_regression=0.20,
        min_format_rows=20,
        max_format_brier_regression=0.02,
        bootstrap_samples=400,
    )

    assert result.artifact.version == "draft-survival-logit-v2-chronological"
    assert result.artifact.promoted is True
    assert result.report["evaluation"]["split_kind"] == "timestamp"
    assert result.report["market_verified_rate"] == 1.0
    assert result.report["model_metrics"]["brier"] < result.report["baselines"]["normal_adp"]["brier"]
    assert (
        result.report["model_metrics"]["brier"]
        < result.report["baselines"]["empirical_adp_bucket"]["brier"]
    )
    bootstrap = result.report["paired_draft_room_bootstrap"]
    assert bootstrap["ci_low"] > 0.0
    assert bootstrap["p_value"] > 0.0
    assert bootstrap["room_consistency"] == 1.0
    assert result.report["adp_calibration_slices"]
    assert result.report["promotion"]["blockers"] == []


def test_overall_market_lift_cannot_hide_supported_format_regression() -> None:
    result = train_chronological_survival_model(
        _format_regression_observations(),
        min_rows=400,
        min_drafts=12,
        test_fraction=0.25,
        min_holdout_drafts=2,
        min_brier_improvement=0.001,
        max_ece_regression=0.50,
        min_format_rows=20,
        max_format_brier_regression=0.05,
        bootstrap_samples=400,
    )

    assert float(result.artifact.metrics["brier_improvement"]) > 0.0
    assert result.artifact.promoted is False
    assert "format_slice_brier_regression" in result.report["promotion"]["blockers"]
    regressions = [
        row
        for row in result.report["format_slices"]
        if row["brier_regression_vs_best_baseline"] > 0.05
    ]
    assert regressions
    assert any("half_ppr" in row["format_key"] for row in regressions)


def test_row_weighted_lift_cannot_hide_draft_room_fragility() -> None:
    result = train_chronological_survival_model(
        _room_fragility_observations(),
        min_rows=400,
        min_drafts=15,
        test_fraction=0.25,
        min_holdout_drafts=5,
        min_brier_improvement=0.001,
        max_ece_regression=0.50,
        min_format_rows=20,
        max_format_brier_regression=0.50,
        min_draft_consistency=0.60,
        bootstrap_samples=500,
    )

    assert float(result.artifact.metrics["brier_improvement"]) > 0.0
    assert result.report["paired_draft_room_bootstrap"]["room_consistency"] < 0.60
    assert result.artifact.promoted is False
    assert "draft_room_consistency_below_gate" in result.report["promotion"]["blockers"]


def test_unverified_market_blocks_promotion_even_when_model_has_signal() -> None:
    result = train_chronological_survival_model(
        _market_observations(verified=False),
        min_rows=200,
        min_drafts=8,
        test_fraction=0.25,
        min_holdout_drafts=2,
        min_brier_improvement=0.0,
        max_ece_regression=0.20,
        min_format_rows=20,
        max_format_brier_regression=0.05,
        bootstrap_samples=400,
    )

    assert result.artifact.promoted is False
    assert result.report["market_verified_rate"] == 0.0
    assert "point_in_time_market_not_fully_verified" in result.report["promotion"]["blockers"]


def _historical_draft_rows(*, market_after_draft: bool = False) -> pd.DataFrame:
    draft_time = datetime(2025, 8, 10, 18, tzinfo=UTC)
    market_time = draft_time + timedelta(hours=1 if market_after_draft else -6)
    rows: list[dict[str, object]] = []
    for pick in range(1, 13):
        rows.append(
            {
                "draft_id": "room-a",
                "player_id": f"p{pick:02d}",
                "actual_pick": pick,
                "market_adp": float(pick + (pick % 3) - 1),
                "market_adp_sd": 4.0,
                "position": "WR" if pick % 2 else "RB",
                "teams": 4,
                "draft_started_at": draft_time.isoformat(),
                "market_snapshot_at": market_time.isoformat(),
                "season": 2025,
                "platform": "sleeper",
                "scoring": "ppr",
            }
        )
    return pd.DataFrame(rows)


def test_observation_builder_rejects_post_draft_market_snapshot() -> None:
    with pytest.raises(ValueError, match="captured after its draft started"):
        build_observations(_historical_draft_rows(market_after_draft=True), default_teams=4)


def test_observation_builder_records_point_in_time_supply_without_outcome_features() -> None:
    observations = build_observations(_historical_draft_rows(), default_teams=4)

    assert not observations.empty
    assert observations["point_in_time_market_verified"].all()
    assert (observations["market_snapshot_age_hours"] == 6.0).all()
    assert {
        "current_round",
        "next_pick_round",
        "position_market_rank",
        "position_supply_to_next",
        "position_supply_next_round",
        "draft_market_depth",
        "recent_position_run",
    }.issubset(observations.columns)
    assert (observations["position_supply_next_round"] >= observations["position_supply_to_next"]).all()
    assert "fantasy_points" not in observations.columns
