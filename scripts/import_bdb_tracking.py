#!/usr/bin/env python3
"""Convert an authorized local BDB 2025 or original 2019 tracking CSV into research JSON.

Example:
  python scripts/import_bdb_tracking.py \
    --csv /private/bdb2025/tracking_week_1.csv \
    --game-id 2024090800 --play-id 12 \
    --license-id "terms-reviewed" --acknowledge-source-terms \
    --output /tmp/pse-replays/2024090800-12.json

WARNING: This utility grants no rights to use, train on, publish or redistribute
NFL/BDB data. Follow the actual contest and provider terms.
"""
from __future__ import annotations

import argparse

from player_state_engine.product.gameday_legacy_tracking import import_bdb_2019_example
from player_state_engine.product.gameday_tracking import (
    import_bdb_2025_tracking,
    write_replay_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="Local tracking CSV file")
    parser.add_argument("--format", choices=["bdb2025", "bdb2019"], default="bdb2025")
    parser.add_argument("--offense-side", choices=["home", "away"], help="For bdb2019: verified possession team side from play and game metadata")
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--play-id", required=True)
    parser.add_argument("--possession-team", help="Offense team abbreviation, if independently verified")
    parser.add_argument("--license-id", required=True, help="Source-specific terms/license you reviewed")
    parser.add_argument(
        "--acknowledge-source-terms", action="store_true",
        help="Confirm authorized access and applicable research/reuse restrictions",
    )
    parser.add_argument("--output", required=True, help="Output research-only JSON file")
    args = parser.parse_args()
    if args.format == "bdb2019":
        if args.possession_team:
            parser.error("--possession-team is for bdb2025 only; use --offense-side for bdb2019.")
        result = import_bdb_2019_example(
            args.csv,
            game_id=args.game_id,
            play_id=args.play_id,
            offense_side=args.offense_side,
            license_acknowledged=args.acknowledge_source_terms,
            license_identifier=args.license_id,
        )
    else:
        if args.offense_side:
            parser.error("--offense-side is for bdb2019 only.")
        result = import_bdb_2025_tracking(
            args.csv,
            game_id=args.game_id,
            play_id=args.play_id,
            possession_team=args.possession_team,
            license_acknowledged=args.acknowledge_source_terms,
            license_identifier=args.license_id,
        )
    path = write_replay_json(result, args.output)
    print(
        "Saved HISTORICAL_RESEARCH replay to " + str(path) + ": "
        + str(result["frame_count"]) + " frames, "
        + str(result["missing_frame_count"]) + " missing, "
        + str(result["rows"]) + " source rows. NOT LIVE; NOT COMMERCIAL."
    )


if __name__ == "__main__":
    main()
