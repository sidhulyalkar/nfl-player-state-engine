"""Run local rookie-season game tracking audit; no downloads or model promotion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.research.bdb27_nfl import run_rookie_game_audit
from player_state_engine.research.bdb27_qualification import QualificationConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--position", choices=("DB", "WR", "TE", "OL", "DL"), default="DB")
    parser.add_argument("--rookie-season", type=int, choices=(2023, 2024, 2025), required=True)
    parser.add_argument("--y-axis-sign", type=int, choices=(-1, 1), required=True)
    parser.add_argument("--acknowledge-competition-data-terms", action="store_true", required=True)
    args = parser.parse_args()
    result = run_rookie_game_audit(args.source_dir, args.output_dir,
                                   year=args.rookie_season, position=args.position,
                                   config=QualificationConfig(args.y_axis_sign),
                                   rights_acknowledged=args.acknowledge_competition_data_terms)
    print(json.dumps({"authority": result["authority"], "audit": result["audit"]}, indent=2))


if __name__ == "__main__":
    main()
