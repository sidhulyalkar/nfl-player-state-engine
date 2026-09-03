from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from player_state_engine.data.io import read_table
from player_state_engine.evaluation.weekly_showcase import (
    SnapshotProvenance,
    build_weekly_showcase,
    normalize_actuals_snapshot,
    normalize_expert_snapshot,
    normalize_model_snapshot,
)


def _first_column(frame: pd.DataFrame, candidates: tuple[str, ...], *, label: str) -> str:
    for column in candidates:
        if column in frame.columns:
            return column
    raise ValueError(f"Unable to resolve {label}. Tried: {list(candidates)}")


def _optional_column(frame: pd.DataFrame, requested: str | None, candidates: tuple[str, ...]) -> str | None:
    if requested:
        if requested not in frame.columns:
            raise ValueError(f"Requested column {requested!r} is not present.")
        return requested
    return next((column for column in candidates if column in frame.columns), None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build one immutable weekly model-performance artifact from frozen model, expert, "
            "and actual-outcome snapshots. Expert point projections are optional; ordinal expert "
            "rankings remain a valid comparison baseline."
        )
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--expert", type=Path, required=True)
    parser.add_argument("--actuals", type=Path, required=True)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--scoring", required=True, help="Stable scoring label such as ppr or half_ppr")
    parser.add_argument("--model-captured-at", required=True, help="Timezone-aware ISO timestamp")
    parser.add_argument("--expert-captured-at", required=True, help="Timezone-aware ISO timestamp")
    parser.add_argument("--actuals-captured-at", default=None, help="Timezone-aware ISO timestamp")
    parser.add_argument("--model-source", default="player_state_engine")
    parser.add_argument("--expert-source", default="fantasypros_ecr")
    parser.add_argument("--actuals-source", default="nflverse_scored_actuals")
    parser.add_argument("--model-points-column", default=None)
    parser.add_argument("--model-q10-column", default=None)
    parser.add_argument("--model-q90-column", default=None)
    parser.add_argument("--expert-rank-column", default=None)
    parser.add_argument("--expert-points-column", default=None)
    parser.add_argument("--actual-points-column", default=None)
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/evaluation/showcase"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_raw = read_table(args.model)
    expert_raw = read_table(args.expert)
    actuals_raw = read_table(args.actuals)

    model_points = args.model_points_column or _first_column(
        model_raw,
        (
            "weekly_fantasy_points_q50",
            "fantasy_points_ppr_q50",
            "league_fantasy_points_q50",
            "week_q50",
            "q50",
            "projected_points",
            "projection",
        ),
        label="model point projection column",
    )
    model_q10 = _optional_column(
        model_raw,
        args.model_q10_column,
        ("weekly_fantasy_points_q10", "fantasy_points_ppr_q10", "league_fantasy_points_q10", "week_q10", "q10"),
    )
    model_q90 = _optional_column(
        model_raw,
        args.model_q90_column,
        ("weekly_fantasy_points_q90", "fantasy_points_ppr_q90", "league_fantasy_points_q90", "week_q90", "q90"),
    )
    expert_rank = args.expert_rank_column or _first_column(
        expert_raw,
        ("rank", "rank_ecr", "overall_rank", "expert_rank", "position_rank"),
        label="expert rank column",
    )
    expert_points = _optional_column(
        expert_raw,
        args.expert_points_column,
        ("projected_points", "projection", "fantasy_points", "points"),
    )
    actual_points = args.actual_points_column or _first_column(
        actuals_raw,
        ("fantasy_points", "fantasy_points_ppr", "league_fantasy_points", "actual_points", "actual", "points"),
        label="actual fantasy-point column",
    )

    model = normalize_model_snapshot(
        model_raw,
        points_column=model_points,
        q10_column=model_q10,
        q90_column=model_q90,
    )
    expert = normalize_expert_snapshot(
        expert_raw,
        rank_column=expert_rank,
        points_column=expert_points,
    )
    actuals = normalize_actuals_snapshot(actuals_raw, points_column=actual_points)
    actuals_captured_at = args.actuals_captured_at or datetime.now(UTC).isoformat()

    manifest = build_weekly_showcase(
        model=model,
        expert=expert,
        actuals=actuals,
        season=args.season,
        week=args.week,
        scoring=args.scoring,
        model_provenance=SnapshotProvenance(
            source=args.model_source,
            captured_at_utc=args.model_captured_at,
            source_path=str(args.model),
        ),
        expert_provenance=SnapshotProvenance(
            source=args.expert_source,
            captured_at_utc=args.expert_captured_at,
            source_path=str(args.expert),
        ),
        actuals_provenance=SnapshotProvenance(
            source=args.actuals_source,
            captured_at_utc=actuals_captured_at,
            source_path=str(args.actuals),
        ),
        output_root=args.output_root,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
