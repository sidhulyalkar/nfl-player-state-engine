from __future__ import annotations

import argparse
from pathlib import Path

from player_state_engine.data.historical import acquire_historical_sources

parser = argparse.ArgumentParser()
parser.add_argument("--seasons", nargs="+", type=int, default=list(range(2020, 2026)))
parser.add_argument("--output-dir", type=Path, default=Path("data/raw/historical_sources"))
parser.add_argument("--without-participation", action="store_true")
parser.add_argument("--without-pbp", action="store_true")
args = parser.parse_args()
manifest = acquire_historical_sources(
    args.seasons, args.output_dir,
    include_participation=not args.without_participation,
    include_pbp=not args.without_pbp,
)
print(manifest.to_string(index=False))
