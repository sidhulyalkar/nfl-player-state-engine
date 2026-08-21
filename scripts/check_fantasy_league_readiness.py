from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.data.io import read_table
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import assess_league_readiness


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit projection readiness for a fantasy league.")
    parser.add_argument("--projections", type=Path, required=True)
    parser.add_argument("--league", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when the league is not ready")
    args = parser.parse_args()

    projections = read_table(args.projections)
    league = LeagueConfig.from_yaml(args.league)
    report = assess_league_readiness(projections, league)
    payload = report.as_dict()
    print(json.dumps(payload, indent=2, default=str))
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(payload, indent=2, default=str))
    if args.strict and not report.ready:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
