#!/usr/bin/env python3
"""Export local source-verified NFL game/play metadata without player positions."""
from __future__ import annotations

import argparse

from player_state_engine.product.bdb2019_game_timeline import (
    build_bdb2019_game_timeline,
    write_game_timeline,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, help="Directory with original pinned tracking/plays/games CSVs")
    parser.add_argument("--catalog", required=True, help="Previously validated position-free play catalog JSON")
    parser.add_argument("--output", required=True, help="Private local game timeline JSON")
    parser.add_argument("--license-id", required=True, help="Identifier of actual source-use terms reviewed")
    parser.add_argument("--acknowledge-source-terms", action="store_true")
    options = parser.parse_args()
    result = build_bdb2019_game_timeline(
        options.source_dir, options.catalog,
        license_acknowledged=options.acknowledge_source_terms,
        license_identifier=options.license_id,
    )
    target = write_game_timeline(result, options.output)
    print(f"Verified source metadata: {result['play_count']} plays -> {target}")
    print("Tracking coordinates, live game state, inferred drives and coaching grades are absent.")


if __name__ == "__main__":
    main()
