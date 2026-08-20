from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.data.io import read_table, write_table
from player_state_engine.player_state.benchmark import (
    compare_forecasts,
    grouped_forecast_scorecards,
)


def _models(value: str) -> tuple[str, ...]:
    models = tuple(part.strip() for part in value.split(",") if part.strip())
    if len(models) < 2:
        raise argparse.ArgumentTypeError("provide at least two comma-separated model prefixes")
    return models


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate direct/world/graph/fusion probabilistic forecasts on a frozen archive."
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--models", type=_models, default=("direct", "graph", "fusion"))
    parser.add_argument("--reference", default="direct")
    parser.add_argument("--actual-column", default="actual")
    parser.add_argument("--minimum-group-rows", type=int, default=30)
    parser.add_argument("--bootstrap-samples", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/reports/player_forecast_benchmark"),
    )
    args = parser.parse_args()

    archive = read_table(args.archive)
    models = tuple(args.models)
    if args.reference not in models:
        raise SystemExit(f"reference model {args.reference!r} must be included in --models")

    scorecards = grouped_forecast_scorecards(
        archive,
        models=models,
        actual_column=args.actual_column,
        minimum_rows=args.minimum_group_rows,
    )
    comparisons: list[dict[str, object]] = []
    for model in models:
        if model == args.reference:
            continue
        comparison = compare_forecasts(
            archive,
            candidate=model,
            reference=args.reference,
            actual_column=args.actual_column,
            bootstrap_samples=args.bootstrap_samples,
            seed=args.seed,
        )
        comparisons.append(comparison.as_dict())

    args.output_dir.mkdir(parents=True, exist_ok=True)
    scorecard_path = write_table(scorecards, args.output_dir / "scorecards.csv")
    comparison_path = args.output_dir / "comparisons.json"
    comparison_path.write_text(json.dumps(comparisons, indent=2, default=str))

    print(scorecards.loc[scorecards["group"].eq("overall")].to_string(index=False))
    print("\nPaired WIS comparisons against reference:")
    print(json.dumps(comparisons, indent=2, default=str))
    print(f"\nWrote {scorecard_path}")
    print(f"Wrote {comparison_path}")


if __name__ == "__main__":
    main()
