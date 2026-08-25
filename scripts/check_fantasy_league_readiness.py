from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.data.io import read_table
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import assess_league_readiness


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Audit whether a projection artifact is sufficiently complete for one fantasy "
            "league's roster, scoring, identity, valuation, and draft-market requirements."
        )
    )
    parser.add_argument("--projections", type=Path, required=True)
    parser.add_argument("--league", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 2 when blocking readiness findings remain.",
    )
    parser.add_argument("--minimum-market-coverage", type=float, default=0.70)
    parser.add_argument("--minimum-exact-scoring-coverage", type=float, default=0.80)
    parser.add_argument("--minimum-valuation-coverage", type=float, default=0.98)
    parser.add_argument("--minimum-ready-score", type=float, default=65.0)
    args = parser.parse_args()

    projections = read_table(args.projections)
    config = LeagueConfig.from_yaml(args.league)
    report = assess_league_readiness(
        projections,
        config,
        minimum_market_coverage=args.minimum_market_coverage,
        minimum_exact_scoring_coverage=args.minimum_exact_scoring_coverage,
        minimum_valuation_coverage=args.minimum_valuation_coverage,
        minimum_ready_score=args.minimum_ready_score,
    )
    payload = report.as_dict()
    rendered = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    print(rendered, end="")
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered, encoding="utf-8")
    if args.strict and not report.ready:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
