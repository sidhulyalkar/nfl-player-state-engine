from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.product.nfl_hub import refresh_nfl_hub


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh the source-aware NFL Hub snapshot from maintained nflverse sources."
    )
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--root", type=Path, default=Path("data/product/nfl_hub"))
    parser.add_argument(
        "--projections",
        type=Path,
        default=None,
        help=(
            "Optional read-only, single-contract projection context. Omit for the default "
            "observational Hub; do not pass the multicontract production draft artifact."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot = refresh_nfl_hub(
        season=args.season,
        root=args.root,
        projections_path=args.projections,
    )
    print(
        json.dumps(
            {
                "status": snapshot["status"],
                "season": snapshot["season"],
                "player_count": snapshot["player_count"],
                "event_count": snapshot["event_count"],
                "optional_source_failures": snapshot["optional_source_failures"],
                "generated_at_utc": snapshot["generated_at_utc"],
                "projection_context_configured": args.projections is not None,
                "snapshot": str(args.root / "current.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
