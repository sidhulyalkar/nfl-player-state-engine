from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from player_state_engine.fantasy.draft_market_ablation import evaluate_supply_feature_ablation


def _supply_signal_observations() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    start = datetime(2024, 5, 1, tzinfo=UTC)
    for draft_index in range(20):
        draft_time = start + timedelta(days=5 * draft_index)
        for row_index in range(40):
            supply = row_index % 4 + 1
            rows.append(
                {
                    "draft_id": f"supply-{draft_index:02d}",
                    "draft_started_at": draft_time.isoformat(),
                    "point_in_time_market_verified": True,
                    "current_pick": 20,
                    "next_pick": 31,
                    "market_adp": 30.0,
                    "market_adp_sd": 8.0,
                    "teams": 10,
                    "position": "WR",
                    "platform": "sleeper",
                    "scoring": "ppr",
                    "qb_slots_per_team": 2,
                    "superflex_slots_per_team": 0,
                    "starter_slots_per_team": 10,
                    "recent_position_run": 0,
                    "position_market_rank": 10 - supply,
                    "position_supply_to_next": supply,
                    "position_supply_next_round": supply + 2,
                    "draft_market_depth": 50 + supply,
                    "survived_to_next_pick": int(supply >= 3),
                }
            )
    return pd.DataFrame(rows)


def test_supply_ablation_detects_incremental_room_state_signal() -> None:
    report = evaluate_supply_feature_ablation(
        _supply_signal_observations(),
        min_rows=400,
        min_drafts=15,
        test_fraction=0.25,
        min_holdout_drafts=5,
        min_brier_improvement=0.001,
        max_ece_regression=0.10,
        min_format_rows=20,
        max_format_brier_regression=0.02,
        min_draft_consistency=0.60,
        bootstrap_samples=400,
    )

    assert report["authority"] == "research_challenger_only"
    assert report["live_authority_changed"] is False
    assert report["automatic_promotion"] is False
    assert report["supply_challenger"]["brier"] < report["base_model"]["brier"]
    assert report["incremental_brier_improvement"] > 0.0
    assert report["paired_draft_room_bootstrap"]["ci_low"] > 0.0
    assert report["paired_draft_room_bootstrap"]["room_consistency"] == 1.0
    assert report["next_stage"]["eligible_for_downstream_replay"] is True
    assert report["next_stage"]["blockers"] == []


def test_supply_ablation_fails_closed_when_market_fields_are_missing() -> None:
    observations = _supply_signal_observations().drop(columns=["position_supply_to_next"])

    with pytest.raises(ValueError, match="Supply ablation requires timestamp-safe market fields"):
        evaluate_supply_feature_ablation(
            observations,
            min_rows=400,
            min_drafts=15,
            test_fraction=0.25,
            min_holdout_drafts=5,
            bootstrap_samples=400,
        )


def test_supply_ablation_does_not_clear_when_holdout_relationship_reverses() -> None:
    observations = _supply_signal_observations()
    late_rooms = {f"supply-{index:02d}" for index in range(15, 20)}
    mask = observations["draft_id"].isin(late_rooms)
    observations.loc[mask, "survived_to_next_pick"] = (
        1 - observations.loc[mask, "survived_to_next_pick"].astype(int)
    )

    report = evaluate_supply_feature_ablation(
        observations,
        min_rows=400,
        min_drafts=15,
        test_fraction=0.25,
        min_holdout_drafts=5,
        min_brier_improvement=0.001,
        max_ece_regression=0.50,
        min_format_rows=20,
        max_format_brier_regression=0.50,
        min_draft_consistency=0.60,
        bootstrap_samples=400,
    )

    assert report["next_stage"]["eligible_for_downstream_replay"] is False
    assert report["next_stage"]["blockers"]
