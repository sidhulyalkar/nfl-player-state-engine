from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.data.io import write_table
from player_state_engine.fantasy.draft_market_archive import normalize_archive
from player_state_engine.fantasy.draft_market_processed import resolve_processed_player_identity


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify and normalize immutable Sleeper draft archives into realized pick rows."
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=Path("data/external/drafts/sleeper"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/historical_sleeper_drafts.parquet"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/draft_market/archive_normalization.json"),
    )
    args = parser.parse_args()

    frame, report = normalize_archive(args.archive_root)
    frame = resolve_processed_player_identity(frame)
    if not frame.empty:
        report["player_identity"] = "canonical_player_id_then_sleeper_platform_player_id"
    output = write_table(frame, args.output)
    report["output"] = str(output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
