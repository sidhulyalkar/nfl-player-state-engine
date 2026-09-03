from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from player_state_engine.evaluation.showcase_automation import resolve_regular_season_week

SCHEDULE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"


def _download_schedule(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        SCHEDULE_URL,
        headers={"User-Agent": "NFLPlayerStateEngine/showcase-automation"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        path.write_bytes(response.read())
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve the regular-season week for weekly showcase capture or settlement."
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--phase", choices=["capture", "settle"], required=True)
    parser.add_argument("--week", type=int, default=None, help="Explicit override; skips inference")
    parser.add_argument("--as-of", default=None, help="ISO date/time; defaults to current UTC time")
    parser.add_argument("--schedule", type=Path, default=None)
    parser.add_argument(
        "--download-path",
        type=Path,
        default=Path("data/raw/nflverse/showcase_games.csv"),
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        default=None,
        help="Optional GitHub Actions output file; writes week=<resolved week>",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.week is not None:
        if not 1 <= int(args.week) <= 18:
            raise ValueError("--week must be between 1 and 18")
        week = int(args.week)
        resolution = "explicit"
        schedule_path = None
    else:
        schedule_path = args.schedule or _download_schedule(args.download_path)
        schedule = pd.read_csv(schedule_path, low_memory=False)
        as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp(datetime.now(UTC))
        week = resolve_regular_season_week(
            schedule,
            season=args.season,
            phase=args.phase,
            as_of=as_of,
        )
        resolution = "nflverse_schedule"

    output_path = args.github_output
    if output_path is None and os.getenv("GITHUB_OUTPUT"):
        output_path = Path(os.environ["GITHUB_OUTPUT"])
    if output_path is not None:
        with output_path.open("a", encoding="utf-8") as handle:
            handle.write(f"week={week}\n")

    print(
        json.dumps(
            {
                "season": args.season,
                "week": week,
                "phase": args.phase,
                "resolution": resolution,
                "schedule_path": str(schedule_path) if schedule_path else None,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
