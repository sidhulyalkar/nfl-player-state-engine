from __future__ import annotations

import argparse
from pathlib import Path

from player_state_engine.data.io import read_table, write_table
from player_state_engine.fantasy.rankings import normalize_ranking_frame


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize a licensed/user-provided ranking or ADP export into the timestamped "
            "external-ranking schema. No page scraping is performed."
        )
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-kind", choices=["expert", "market", "sharp_market", "projection"], default=None)
    parser.add_argument("--ranking-type", default="draft")
    parser.add_argument("--scoring", default="unknown")
    parser.add_argument("--teams", type=int, default=None)
    parser.add_argument("--qb-format", choices=["unknown", "1qb", "2qb", "superflex"], default="unknown")
    parser.add_argument("--captured-at", default=None, help="ISO-8601 timestamp; default is current UTC time")
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--source-weight", type=float, default=1.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    raw = read_table(args.input)
    normalized = normalize_ranking_frame(
        raw,
        source=args.source,
        source_kind=args.source_kind,
        ranking_type=args.ranking_type,
        scoring=args.scoring,
        teams=args.teams,
        qb_format_name=args.qb_format,
        source_weight=args.source_weight,
        captured_at_utc=args.captured_at,
        source_url=args.source_url,
    )
    path = write_table(normalized, Path(args.output))
    print(path)
    print(f"rows={len(normalized)}")


if __name__ == "__main__":
    main()
