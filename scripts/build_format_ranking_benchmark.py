from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.data.io import read_table, write_table
from player_state_engine.evaluation.ranking_validation import (
    default_format_scenarios,
    evaluate_ranking_promotion,
    run_format_matrix,
    structural_monotonicity_checks,
)
from player_state_engine.fantasy.rankings import load_ranking_snapshots


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark fantasy ranking behavior across league size, QB format and scoring."
    )
    parser.add_argument("--projections", required=True)
    parser.add_argument("--rankings-root", default=None)
    parser.add_argument("--output-dir", default="artifacts/evaluation/ranking_formats")
    parser.add_argument("--candidate", default="dynamic_scarcity_challenger_v09")
    parser.add_argument("--baseline", default="live_draft_score_v08")
    parser.add_argument("--historical-candidate-utility", type=float, default=None)
    parser.add_argument("--historical-baseline-utility", type=float, default=None)
    parser.add_argument("--allow-no-historical-utility", action="store_true")
    args = parser.parse_args()

    projections = read_table(args.projections)
    rankings = load_ranking_snapshots(args.rankings_root) if args.rankings_root else None
    scenarios = default_format_scenarios()
    boards, summary, external_metrics = run_format_matrix(
        projections, scenarios=scenarios, rankings=rankings
    )
    checks = structural_monotonicity_checks(boards, summary)
    gate = evaluate_ranking_promotion(
        checks,
        candidate=args.candidate,
        baseline=args.baseline,
        historical_candidate_utility=args.historical_candidate_utility,
        historical_baseline_utility=args.historical_baseline_utility,
        require_historical_utility=not args.allow_no_historical_utility,
    )

    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    write_table(summary, root / "format_position_summary.csv")
    if not external_metrics.empty:
        write_table(external_metrics, root / "external_ranking_metrics.csv")
    board_dir = root / "boards"
    for name, board in boards.items():
        write_table(board, board_dir / f"{name}.parquet")
    report = {
        "scenarios": [
            {"name": scenario.name, "tags": scenario.tags, "config": scenario.config.__dict__ if hasattr(scenario.config, "__dict__") else {
                "teams": scenario.config.teams,
                "scoring": scenario.config.scoring,
                "roster_slots": scenario.config.roster_slots,
                "tight_end_premium": scenario.config.tight_end_premium,
                "median_scoring": scenario.config.median_scoring,
            }}
            for scenario in scenarios
        ],
        "structural_checks": [check.to_dict() for check in checks],
        "promotion_gate": gate.to_dict(),
    }
    report_path = root / "report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(report_path)
    print(f"promotion={gate.promoted} reason={gate.reason}")


if __name__ == "__main__":
    main()
