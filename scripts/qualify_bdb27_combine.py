"""Qualify *local, authorized* BDB27 Combine CSVs without downloading or publishing them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.research.bdb27_qualification import QualificationConfig, qualify_directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True,
                        help="Directory containing authorized players.csv and combine_tracking.csv")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Local research output outside licensed source directory")
    parser.add_argument("--y-axis-sign", type=int, choices=(-1, 1), required=True,
                        help="Explicit raw-to-analysis Y sign, MUST be checked with source documentation")
    parser.add_argument("--acknowledge-competition-data-terms", action="store_true", required=True)
    args = parser.parse_args()
    result = qualify_directory(
        args.source_dir, args.output_dir, QualificationConfig(args.y_axis_sign),
        source_rights_acknowledged=args.acknowledge_competition_data_terms,
    )
    print(json.dumps({"authority": result["authority"],
                      "source_status": result["source_status"],
                      "audit": result["audit"]}, indent=2))


if __name__ == "__main__":
    main()
