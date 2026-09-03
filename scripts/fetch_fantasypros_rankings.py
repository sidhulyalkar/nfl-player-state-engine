from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from player_state_engine.data.io import write_table
from player_state_engine.integrations.fantasypros import FantasyProsClient


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a point-in-time FantasyPros consensus/ADP snapshot through the official API."
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, default=0, help="0 for preseason/draft ECR; 1+ for weekly ECR")
    parser.add_argument("--position", default="ALL")
    parser.add_argument("--scoring", choices=["STD", "HALF", "PPR"], default="HALF")
    parser.add_argument("--ranking-type", default=None, help="e.g. ADP, ROS, DK; omit for ECR")
    parser.add_argument("--teams", type=int, default=None)
    parser.add_argument(
        "--qb-format", choices=["unknown", "1qb", "2qb", "superflex"], default="unknown"
    )
    parser.add_argument("--filters", default=None, help="Optional colon-delimited FantasyPros expert IDs")
    parser.add_argument("--output-root", default="data/external/rankings/fantasypros")
    args = parser.parse_args()

    client = FantasyProsClient()
    frame, metadata = client.fetch_consensus_rankings(
        args.season,
        position=args.position,
        scoring=args.scoring,
        ranking_type=args.ranking_type,
        week=args.week,
        teams=args.teams,
        qb_format_name=args.qb_format,
        filters=args.filters,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    ranking_label = str(args.ranking_type or "ecr").lower()
    week_label = f"w{args.week:02d}" if args.week else "preseason"
    stem = f"{args.season}_{week_label}_{args.scoring.lower()}_{args.qb_format}_{args.position.lower()}_{ranking_label}_{timestamp}"
    root = Path(args.output_root)
    path = write_table(frame, root / f"{stem}.parquet")
    report_path = root / f"{stem}.metadata.json"
    metadata = {**metadata, "requested_week": int(args.week), "snapshot_file": str(path)}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    print(path)
    print(report_path)


if __name__ == "__main__":
    main()
