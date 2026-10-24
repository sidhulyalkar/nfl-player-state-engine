#!/usr/bin/env python3
"""Create one local, source-verified multi-play research session in one pass.

Never uploads raw tracking, derived replays or provenance identifiers.
Usage:
  python scripts/export_bdb2019_replay_batch.py \
    --source-dir data/external/bdb2019-private \
    --output-dir /tmp/private-nfl-playlab-plays \
    --play-id 938 --play-id 2756 \
    --license-id 'ACTUAL_TERMS_YOU_REVIEWED' --acknowledge-source-terms
"""
from __future__ import annotations

import argparse

from player_state_engine.product.bdb2019_batch_replay import export_bdb2019_replay_batch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir", required=True,
        help="Private directory containing the exact NFL tracking, plays and games CSVs",
    )
    parser.add_argument(
        "--output-dir", required=True,
        help="NEW private destination directory, created atomically after all plays qualify",
    )
    parser.add_argument(
        "--play-id", action="append", dest="plays", required=True,
        help="Numeric official NFL play ID; repeat up to 12 times",
    )
    parser.add_argument(
        "--license-id", required=True,
        help="Identifier of independently reviewed source-use terms, not a new license",
    )
    parser.add_argument(
        "--acknowledge-source-terms", action="store_true",
        help="Affirm that the source-use restrictions were reviewed for this private execution",
    )
    args = parser.parse_args()
    if not args.acknowledge_source_terms or not args.license_id.strip():
        parser.error("Actual source-use terms must be reviewed and expressly acknowledged.")
    manifest = export_bdb2019_replay_batch(
        args.source_dir, args.output_dir,
        play_ids=args.plays,
        license_acknowledged=True, license_identifier=args.license_id,
    )
    print(
        f"Created {manifest['play_count']} recorded historical play JSONs plus "
        f"a manifest in {args.output_dir}."
    )
    print("Private research only: not live, not film-aligned, no commercial or training rights granted.")


if __name__ == "__main__":
    main()
