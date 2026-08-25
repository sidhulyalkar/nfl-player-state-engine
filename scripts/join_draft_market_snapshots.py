from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.data.io import read_table, write_table
from player_state_engine.fantasy.draft_market_archive import asof_join_market_snapshots
from player_state_engine.fantasy.rankings import load_ranking_snapshots


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Join realized historical drafts to the latest compatible pre-draft market snapshot. "
            "Missing market evidence remains missing and is never reconstructed from actual picks."
        )
    )
    parser.add_argument(
        "--drafts",
        type=Path,
        default=Path("data/processed/historical_sleeper_drafts.parquet"),
    )
    parser.add_argument(
        "--rankings-root",
        type=Path,
        default=Path("data/external/rankings"),
    )
    parser.add_argument("--source", default=None)
    parser.add_argument("--ranking-type", default="adp")
    parser.add_argument("--max-snapshot-age-days", type=float, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/historical_drafts_with_market.parquet"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/draft_market/market_join.json"),
    )
    args = parser.parse_args()

    drafts = read_table(args.drafts)
    rankings = load_ranking_snapshots(args.rankings_root)
    joined, report = asof_join_market_snapshots(
        drafts,
        rankings,
        source=args.source,
        ranking_type=args.ranking_type,
        max_snapshot_age_days=args.max_snapshot_age_days,
    )
    output = write_table(joined, args.output)
    report["drafts_input"] = str(args.drafts)
    report["rankings_root"] = str(args.rankings_root)
    report["output"] = str(output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
