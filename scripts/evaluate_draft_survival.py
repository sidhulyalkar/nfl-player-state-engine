from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from player_state_engine.data.io import read_table, write_table
from player_state_engine.fantasy.draft_evaluation import (
    compare_survival_models_paired,
    grouped_survival_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate archived draft survival predictions on frozen historical rooms."
    )
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--baseline-column", default="survival_to_next_pick")
    parser.add_argument("--challenger-column", default="room_survival_to_next_pick")
    parser.add_argument("--outcome-column", default="survived_to_next_pick")
    parser.add_argument("--baseline-name", default="baseline")
    parser.add_argument("--challenger-name", default="room_challenger")
    parser.add_argument("--minimum-group-rows", type=int, default=30)
    parser.add_argument("--bootstrap-samples", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/reports/draft_survival"),
    )
    args = parser.parse_args()

    history = read_table(args.history)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    baseline = grouped_survival_report(
        history,
        model=args.baseline_name,
        prediction_column=args.baseline_column,
        outcome_column=args.outcome_column,
        minimum_rows=args.minimum_group_rows,
    )
    challenger = grouped_survival_report(
        history,
        model=args.challenger_name,
        prediction_column=args.challenger_column,
        outcome_column=args.outcome_column,
        minimum_rows=args.minimum_group_rows,
    )
    report = pd.concat([baseline, challenger], ignore_index=True)
    comparison = compare_survival_models_paired(
        history,
        challenger_column=args.challenger_column,
        baseline_column=args.baseline_column,
        challenger_name=args.challenger_name,
        baseline_name=args.baseline_name,
        outcome_column=args.outcome_column,
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
    )

    metrics_path = write_table(report, args.output_dir / "survival_metrics.csv")
    comparison_path = args.output_dir / "paired_comparison.json"
    comparison_path.write_text(json.dumps(comparison.as_dict(), indent=2))
    print(report.to_string(index=False))
    print("\nPaired comparison:")
    print(json.dumps(comparison.as_dict(), indent=2))
    print(f"\nWrote {metrics_path}")
    print(f"Wrote {comparison_path}")


if __name__ == "__main__":
    main()
