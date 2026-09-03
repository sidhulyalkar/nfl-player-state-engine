from __future__ import annotations

import json

import pandas as pd
import pytest

from player_state_engine.evaluation.weekly_showcase import (
    SnapshotProvenance,
    WeeklyShowcaseStore,
    build_weekly_showcase,
    evaluate_weekly_showcase,
    normalize_actuals_snapshot,
    normalize_expert_snapshot,
    normalize_model_snapshot,
)


def _snapshots(*, with_expert_points: bool = False):
    model_raw = pd.DataFrame(
        {
            "player_id": ["qb1", "qb2", "rb1", "rb2", "wr1", "wr2", "te1", "te2"],
            "player_name": ["QB One", "QB Two", "RB One", "RB Two", "WR One", "WR Two", "TE One", "TE Two"],
            "position": ["QB", "QB", "RB", "RB", "WR", "WR", "TE", "TE"],
            "recent_team": ["A", "B", "C", "D", "E", "F", "G", "H"],
            "q10": [15, 12, 10, 8, 11, 9, 7, 6],
            "q50": [24, 18, 20, 12, 19, 13, 14, 9],
            "q90": [33, 25, 28, 18, 27, 19, 21, 13],
        }
    )
    expert_data: dict[str, object] = {
        "player_id": ["qb1", "qb2", "rb1", "rb2", "wr1", "wr2", "te1", "te2"],
        "position": ["QB", "QB", "RB", "RB", "WR", "WR", "TE", "TE"],
        "position_rank": [2, 1, 2, 1, 2, 1, 2, 1],
    }
    if with_expert_points:
        expert_data["projected_points"] = [16, 25, 11, 22, 12, 21, 8, 17]
    expert_raw = pd.DataFrame(expert_data)
    actual_raw = pd.DataFrame(
        {
            "player_id": ["qb1", "qb2", "rb1", "rb2", "wr1", "wr2", "te1", "te2"],
            "actual_points": [25, 17, 21, 10, 20, 12, 15, 8],
        }
    )
    return (
        normalize_model_snapshot(model_raw, points_column="q50", q10_column="q10", q90_column="q90"),
        normalize_expert_snapshot(
            expert_raw,
            rank_column="position_rank",
            points_column="projected_points" if with_expert_points else None,
        ),
        normalize_actuals_snapshot(actual_raw, points_column="actual_points"),
    )


def test_rank_only_showcase_compares_position_ranks_without_inventing_expert_points() -> None:
    model, expert, actuals = _snapshots()

    players, metrics, narrative = evaluate_weekly_showcase(model, expert, actuals)

    assert metrics["primary_comparison_metric"] == "position_rank_mae"
    assert metrics["winner"] == "model"
    assert metrics["overall"]["expert_mae"] is None
    assert metrics["overall"]["model_rank_mae"] == 0.0
    assert metrics["overall"]["expert_rank_mae"] == 1.0
    assert set(metrics["position_battles"]) == {"QB", "RB", "WR", "TE"}
    assert all(battle["winner"] == "model" for battle in metrics["position_battles"].values())
    assert narrative["winner"] == "model"
    assert players["rank_edge_vs_expert"].min() == 1.0


def test_expert_points_enable_fantasy_point_mae_battle() -> None:
    model, expert, actuals = _snapshots(with_expert_points=True)

    _players, metrics, _narrative = evaluate_weekly_showcase(model, expert, actuals)

    assert metrics["primary_comparison_metric"] == "fantasy_points_mae"
    assert metrics["overall"]["expert_mae"] is not None
    assert metrics["overall"]["model_mae_advantage"] > 0
    assert metrics["winner"] == "model"


def test_build_weekly_showcase_is_content_addressed_and_idempotent(tmp_path) -> None:
    model, expert, actuals = _snapshots()
    kwargs = dict(
        model=model,
        expert=expert,
        actuals=actuals,
        season=2026,
        week=1,
        scoring="ppr",
        model_provenance=SnapshotProvenance("player_state_engine", "2026-09-10T16:00:00+00:00"),
        expert_provenance=SnapshotProvenance("fantasypros_ecr", "2026-09-10T16:05:00+00:00"),
        actuals_provenance=SnapshotProvenance("nflverse_scored_actuals", "2026-09-14T06:00:00+00:00"),
        output_root=tmp_path,
    )

    first = build_weekly_showcase(**kwargs)
    second = build_weekly_showcase(**kwargs)

    assert first["artifact_id"] == second["artifact_id"]
    assert first["authority"] == "evaluation_only"
    assert first["may_change_production_decisions"] is False
    artifact_root = tmp_path / "2026" / "week_01" / first["artifact_id"]
    assert (artifact_root / "player_deltas.parquet").is_file()
    pointer = json.loads((tmp_path / "2026" / "week_01" / "latest.json").read_text())
    assert pointer["artifact_id"] == first["artifact_id"]

    store = WeeklyShowcaseStore(tmp_path)
    assert store.index()["seasons"][0]["latest_week"] == 1
    week = store.week(2026, 1)
    assert week["metrics"]["winner"] == "model"
    season = store.season(2026)
    assert season["record"] == {"model_wins": 1, "expert_wins": 0, "ties": 0, "unavailable": 0}


def test_showcase_rejects_position_identity_conflicts() -> None:
    model, expert, actuals = _snapshots()
    expert.loc[expert["player_id"].eq("qb1"), "expert_position"] = "RB"

    with pytest.raises(ValueError, match="position identity conflicts"):
        evaluate_weekly_showcase(model, expert, actuals)


def test_showcase_requires_timezone_aware_snapshot_timestamps(tmp_path) -> None:
    model, expert, actuals = _snapshots()

    with pytest.raises(ValueError, match="timezone-aware"):
        build_weekly_showcase(
            model=model,
            expert=expert,
            actuals=actuals,
            season=2026,
            week=1,
            scoring="ppr",
            model_provenance=SnapshotProvenance("player_state_engine", "2026-09-10T16:00:00"),
            expert_provenance=SnapshotProvenance("fantasypros_ecr", "2026-09-10T16:05:00+00:00"),
            actuals_provenance=SnapshotProvenance("nflverse", "2026-09-14T06:00:00+00:00"),
            output_root=tmp_path,
        )
