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
import json
from pathlib import Path

from player_state_engine.product.bdb2019_batch_replay import export_bdb2019_replay_batch
from player_state_engine.product.bdb2019_source_qualification import verify_file_identities

if __package__:
    from .select_bdb2019_pilot import validate_selection
else:
    from select_bdb2019_pilot import validate_selection


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
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--play-id", action="append", dest="plays",
        help="Numeric official NFL play ID; repeat up to 12 times",
    )
    source_group.add_argument(
        "--selection-file", type=Path,
        help="Source-hash-bound, deterministic 12-play selection JSON",
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
    plays = args.plays
    if args.selection_file:
        selection_file = args.selection_file
        if (not selection_file.is_file() or selection_file.is_symlink()
                or selection_file.stat().st_size > 50_000):
            parser.error("Pilot selection must be a bounded, non-symlinked local file")
        selection = json.loads(selection_file.read_text(encoding="utf-8"))
        source_identities = verify_file_identities(Path(args.source_dir))
        plays = validate_selection(
            selection, license_id=args.license_id,
            source_sha256=source_identities["tracking"]["sha256"],
        )
    manifest = export_bdb2019_replay_batch(
        args.source_dir, args.output_dir,
        play_ids=plays,
        license_acknowledged=True, license_identifier=args.license_id,
    )
    print(
        f"Created {manifest['play_count']} recorded historical play JSONs plus "
        f"a manifest in {args.output_dir}."
    )
    print("Private research only: not live, not film-aligned, no commercial or training rights granted.")


if __name__ == "__main__":
    main()
