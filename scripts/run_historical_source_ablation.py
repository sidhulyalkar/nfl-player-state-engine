from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from player_state_engine.data.historical import read_historical_table
from player_state_engine.evaluation.frozen_opportunity import load_frozen_prediction_panel
from player_state_engine.evaluation.historical_sources import (
    build_historical_source_features,
    persist_historical_source_ablation,
    run_historical_source_ablation,
)


def _concat(paths: list[Path]) -> pd.DataFrame | None:
    frames = [read_historical_table(path) for path in paths if path.exists()]
    return pd.concat(frames, ignore_index=True) if frames else None


parser = argparse.ArgumentParser(description="Run frozen ablations for actual historical opportunity and official availability sources.")
parser.add_argument("--data-dir", type=Path, default=Path("data/raw/historical_sources"))
parser.add_argument("--benchmark-root", type=Path, default=Path("artifacts/reports/benchmark_real"))
parser.add_argument("--schedules", type=Path, default=Path("data/raw/nflverse/schedules.parquet"))
parser.add_argument("--output-dir", type=Path, default=Path("artifacts/reports/historical_source_ablation_real"))
args = parser.parse_args()

panel = load_frozen_prediction_panel(args.benchmark_root)
snaps = _concat(sorted(args.data_dir.glob("snap_counts_*.csv")))
rosters = _concat(sorted(args.data_dir.glob("weekly_rosters_*.csv")))
participation = _concat(sorted(args.data_dir.glob("participation_*.parquet")))
pbp = _concat(sorted(args.data_dir.glob("pbp_*.parquet")))
injuries = _concat(sorted(args.data_dir.glob("injuries_*.csv")))
depth = _concat(sorted(args.data_dir.glob("depth_charts_*.rds")))
schedules = read_historical_table(args.schedules) if args.schedules.exists() else None

if all(frame is None for frame in (snaps, participation, injuries, depth)):
    raise SystemExit(
        "No historical source files were found. Run scripts/acquire_historical_sources.py first."
    )
if injuries is not None and schedules is None:
    print("WARNING: injury files found but schedules missing; official same-week availability will not be evaluated.")

features, coverage = build_historical_source_features(
    panel,
    snap_counts=snaps,
    weekly_rosters=rosters,
    participation=participation,
    pbp=pbp,
    injuries=injuries,
    depth_charts=depth,
    schedules=schedules,
)
result = run_historical_source_ablation(features, coverage)
paths = persist_historical_source_ablation(result, args.output_dir)
print(result.summary.to_string(index=False))
print("\nSource coverage:")
print(result.coverage.to_string(index=False))
for name, path in paths.items():
    print(f"{name}: {path}")
