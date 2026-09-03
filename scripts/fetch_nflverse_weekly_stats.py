from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

PLAYER_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_week_{season}.csv"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and freeze nflverse weekly player stats for showcase settlement."
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.week <= 18:
        raise ValueError("--week must be between 1 and 18")

    url = PLAYER_URL.format(season=args.season)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "NFLPlayerStateEngine/showcase-actuals"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310
        raw = response.read()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    season_path = args.output.with_name(f"stats_player_week_{args.season}_full.csv")
    season_path.write_bytes(raw)

    frame = pd.read_csv(season_path, low_memory=False)
    if "season_type" in frame:
        frame = frame.loc[frame["season_type"].astype(str).str.upper().eq("REG")]
    season = pd.to_numeric(frame.get("season"), errors="coerce")
    week = pd.to_numeric(frame.get("week"), errors="coerce")
    selected = frame.loc[season.eq(args.season) & week.eq(args.week)].copy()
    if selected.empty:
        raise ValueError(
            f"nflverse has no completed player-stat rows for {args.season} week {args.week}."
        )
    selected.to_csv(args.output, index=False)

    captured = datetime.now(UTC).isoformat()
    manifest = {
        "source": "nflverse_stats_player_week",
        "source_url": url,
        "captured_at_utc": captured,
        "season": args.season,
        "week": args.week,
        "rows": int(len(selected)),
        "full_source_sha256": _sha256(season_path),
        "week_snapshot_sha256": _sha256(args.output),
        "week_snapshot_path": str(args.output),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
