from __future__ import annotations

import sys

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from player_state_engine.config import load_config
from player_state_engine.data.io import write_table
from player_state_engine.features.weekly import build_weekly_features
from player_state_engine.learning.workflow import continual_update
from run_real_benchmark import acquire_sources, load_regular_season_inputs


def run(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    seasons = tuple(args.seasons or cfg.seasons)
    raw_dir = Path(args.raw_dir)
    output_dir = Path(args.output_dir)
    sources = acquire_sources(
        seasons,
        raw_dir,
        output_dir / "source_manifest.json",
        force=args.force_download,
    )
    stats, schedules = load_regular_season_inputs(sources, seasons)
    features = build_weekly_features(stats, schedules, cfg.features)
    features_path = write_table(features, args.features)

    updated = 0
    for target in args.targets or cfg.model.targets:
        record = continual_update(
            features_path,
            target,
            args.registry,
            output_dir / "candidates",
            cfg,
            force=args.force_retrain,
        )
        if record is not None:
            updated += 1
            print(f"{target}: {record.status} ({record.model_id})")
    print(f"Created {updated} challenger model(s). Automatic promotion={cfg.continual_learning.auto_promote}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh public NFL data and train gated challengers.")
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--raw-dir", default="data/raw/nflverse")
    parser.add_argument("--features", default="data/processed/weekly_features_current.parquet")
    parser.add_argument("--registry", default="artifacts/models/registry.json")
    parser.add_argument("--output-dir", default="artifacts/models")
    parser.add_argument("--seasons", nargs="+", type=int)
    parser.add_argument("--targets", nargs="+")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--force-retrain", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
