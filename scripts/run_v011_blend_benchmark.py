from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from player_state_engine.game_intelligence.blend import expanding_quantile_blend_benchmark


def _read_table(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(source)
    if suffix in {".csv", ".gz"}:
        return pd.read_csv(source)
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(source, lines=suffix == ".jsonl")
    raise ValueError(f"Unsupported table format: {source}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark a leakage-safe direct/generative quantile blend."
    )
    parser.add_argument("--direct", required=True, help="Archived direct-model quantile predictions")
    parser.add_argument("--generative", required=True, help="Archived game-simulator quantile predictions")
    parser.add_argument("--actuals", required=True, help="Realized player fantasy outcomes")
    parser.add_argument("--test-season", action="append", type=int, required=True)
    parser.add_argument("--week-start", type=int, default=1)
    parser.add_argument("--week-end", type=int, default=18)
    parser.add_argument("--min-history-rows", type=int, default=200)
    parser.add_argument("--min-position-rows", type=int, default=100)
    parser.add_argument("--output-dir", default="artifacts/game_intelligence/v011/blend")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = expanding_quantile_blend_benchmark(
        _read_table(args.direct),
        _read_table(args.generative),
        _read_table(args.actuals),
        test_seasons=tuple(args.test_season),
        week_start=args.week_start,
        week_end=args.week_end,
        min_history_rows=args.min_history_rows,
        min_position_rows=args.min_position_rows,
    )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result.weekly_metrics.to_parquet(output / "weekly_blend_metrics.parquet", index=False)
    result.aggregate_metrics.to_parquet(output / "aggregate_blend_metrics.parquet", index=False)
    payload = {
        "diagnostics": result.diagnostics,
        "aggregate_metrics": result.aggregate_metrics.to_dict(orient="records"),
        "production_projection_changed": False,
    }
    (output / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
