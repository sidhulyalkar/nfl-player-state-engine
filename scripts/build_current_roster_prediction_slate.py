from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.config import load_config
from player_state_engine.data.io import read_table, write_table
from player_state_engine.features.serving import build_current_roster_prediction_slate


def run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    stats = read_table(args.stats)
    schedules = read_table(args.schedules)
    rosters = read_table(args.rosters)
    slate, diagnostics = build_current_roster_prediction_slate(
        stats,
        schedules,
        rosters,
        season=args.season,
        week=args.week,
        config=config.features,
        fail_on_unresolved_identity=not args.allow_unresolved_identity,
        fail_on_unknown_status=not args.allow_unknown_status,
        fail_on_ambiguous_team_identity=not args.allow_ambiguous_team_identity,
    )
    output = write_table(slate, args.output)
    diagnostics_path = Path(args.diagnostics)
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_path.write_text(
        json.dumps(diagnostics.as_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(output)
    print(diagnostics_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a future weekly prediction slate from current roster truth."
    )
    parser.add_argument("--stats", required=True)
    parser.add_argument("--schedules", required=True)
    parser.add_argument("--rosters", required=True)
    parser.add_argument("--season", required=True, type=int)
    parser.add_argument("--week", required=True, type=int)
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--output", default="data/processed/current_roster_prediction_slate.parquet")
    parser.add_argument(
        "--diagnostics", default="artifacts/reports/current_roster_prediction_slate.json"
    )
    parser.add_argument("--allow-unresolved-identity", action="store_true")
    parser.add_argument("--allow-unknown-status", action="store_true")
    parser.add_argument("--allow-ambiguous-team-identity", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
