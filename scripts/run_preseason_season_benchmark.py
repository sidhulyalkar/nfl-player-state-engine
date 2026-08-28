from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from player_state_engine.config import load_config
from player_state_engine.data.io import read_table, write_table
from player_state_engine.data.nflverse import download_nflverse
from player_state_engine.evaluation.preseason import (
    PreseasonPromotionGate,
    run_preseason_season_benchmark,
)
from player_state_engine.fantasy.preseason import (
    PRESEASON_TARGETS,
    build_preseason_season_dataset,
    preseason_feature_columns,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _resolve_inputs(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    if args.acquire:
        paths = download_nflverse(args.seasons, args.raw_dir)
        return Path(paths["player_stats"]), Path(paths["rosters_weekly"]), Path(paths["players"])
    if not args.stats or not args.rosters_weekly or not args.players:
        raise ValueError(
            "Provide --stats, --rosters-weekly, and --players, or use --acquire."
        )
    return Path(args.stats), Path(args.rosters_weekly), Path(args.players)


def run(args: argparse.Namespace) -> None:
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stats_path, rosters_path, players_path = _resolve_inputs(args)

    stats = read_table(stats_path)
    rosters = read_table(rosters_path)
    players = read_table(players_path)
    dataset, diagnostics = build_preseason_season_dataset(
        stats,
        rosters,
        players=players,
        seasons=args.seasons,
        snapshot_week=args.snapshot_week,
    )
    dataset_path = write_table(dataset, output / "preseason_season_dataset.parquet")

    config = load_config(args.config)
    targets = tuple(args.targets or PRESEASON_TARGETS)
    model_config = replace(
        config.model,
        targets=targets,
        max_iter=args.max_iter or config.model.max_iter,
        min_samples_leaf=args.min_samples_leaf or config.model.min_samples_leaf,
    )
    policy = PreseasonPromotionGate(
        min_primary_pinball_improvement_pct=args.min_primary_improvement_pct,
        max_component_pinball_regression_pct=args.max_component_regression_pct,
        min_primary_season_win_rate=args.min_season_win_rate,
        max_primary_position_regression_pct=args.max_position_regression_pct,
        max_primary_rookie_regression_pct=args.max_rookie_regression_pct,
        min_rookie_rows=args.min_rookie_rows,
        bootstrap_samples=args.bootstrap_samples,
        random_state=args.seed,
        require_positive_season_bootstrap_ci=not args.allow_nonpositive_bootstrap_ci,
    )
    result = run_preseason_season_benchmark(
        dataset,
        model_config=model_config,
        targets=targets,
        min_train_seasons=args.min_train_seasons,
        gate_policy=policy,
    )

    paths = {
        "dataset": Path(dataset_path),
        "predictions": write_table(result.predictions, output / "predictions.parquet"),
        "summary": write_table(result.summary_metrics, output / "summary_metrics.csv"),
        "season_metrics": write_table(result.season_metrics, output / "season_metrics.csv"),
        "position_metrics": write_table(result.position_metrics, output / "position_metrics.csv"),
        "rookie_metrics": write_table(result.rookie_metrics, output / "rookie_metrics.csv"),
        "comparisons": write_table(result.comparisons, output / "engine_vs_baselines.csv"),
    }
    (output / "dataset_diagnostics.json").write_text(
        json.dumps(diagnostics.as_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    (output / "promotion_gate.json").write_text(
        json.dumps(result.gate.as_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )

    manifest = {
        "schema_version": 1,
        "authority": "research_challenger_only",
        "automatic_promotion": False,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git_sha": os.getenv("GITHUB_SHA"),
        "seasons": [int(value) for value in args.seasons],
        "snapshot_week": int(args.snapshot_week),
        "targets": list(targets),
        "features": preseason_feature_columns(dataset),
        "population_contract": "opening_roster_universe_with_zero_output_seasons",
        "split_contract": "expanding_whole_season_holdout",
        "sources": {
            "player_stats": _source_record(stats_path),
            "rosters_weekly": _source_record(rosters_path),
            "players": _source_record(players_path),
        },
        "dataset_diagnostics": diagnostics.as_dict(),
        "gate": result.gate.as_dict(),
        "eligible_for_activation_review": bool(result.gate.approved),
        "outputs": {name: str(path) for name, path in paths.items()},
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output_dir": str(output),
                "approved": result.gate.approved,
                "blockers": list(result.gate.blockers),
            },
            indent=2,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the direct preseason season-distribution benchmark."
    )
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--seasons", nargs="+", type=int, default=list(range(2015, 2026)))
    parser.add_argument("--snapshot-week", type=int, default=1)
    parser.add_argument("--targets", nargs="+", choices=PRESEASON_TARGETS)
    parser.add_argument("--stats")
    parser.add_argument("--rosters-weekly")
    parser.add_argument("--players")
    parser.add_argument("--acquire", action="store_true")
    parser.add_argument("--raw-dir", default="data/raw/preseason_benchmark")
    parser.add_argument("--output-dir", default="artifacts/reports/preseason_season_benchmark")
    parser.add_argument("--min-train-seasons", type=int, default=4)
    parser.add_argument("--max-iter", type=int)
    parser.add_argument("--min-samples-leaf", type=int)
    parser.add_argument("--min-primary-improvement-pct", type=float, default=1.0)
    parser.add_argument("--max-component-regression-pct", type=float, default=2.0)
    parser.add_argument("--min-season-win-rate", type=float, default=0.60)
    parser.add_argument("--max-position-regression-pct", type=float, default=3.0)
    parser.add_argument("--max-rookie-regression-pct", type=float, default=5.0)
    parser.add_argument("--min-rookie-rows", type=int, default=75)
    parser.add_argument("--bootstrap-samples", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--allow-nonpositive-bootstrap-ci", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
