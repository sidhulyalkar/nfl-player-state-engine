#!/usr/bin/env python3
"""Export a private, metadata-only catalog of official 2017 NFL tracking plays."""
from __future__ import annotations

import argparse

from player_state_engine.product.bdb2019_play_catalog import (
    scan_bdb2019_play_catalog,
    write_play_catalog,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="Local exact BDB2019 official game tracking CSV")
    parser.add_argument("--output", required=True, help="Local JSON catalog destination; no player positions")
    parser.add_argument("--license-id", required=True, help="Actual source-use terms identifier reviewed")
    parser.add_argument("--acknowledge-source-terms", action="store_true")
    options = parser.parse_args()
    if not options.acknowledge_source_terms or not options.license_id.strip():
        parser.error("You must review and acknowledge the source-specific NFL terms.")
    catalog = scan_bdb2019_play_catalog(
        options.csv,
        license_acknowledged=True,
        license_identifier=options.license_id,
    )
    path = write_play_catalog(catalog, options.output)
    print(f"Verified official source -> {catalog['play_count']} metadata-only plays at {path}")
    print("No tracking coordinates exported. Film alignment and commercial use remain unqualified.")


if __name__ == "__main__":
    main()
