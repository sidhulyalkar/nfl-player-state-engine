from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.product.live_adp import refresh_fantasypros_adp_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh the point-in-time FantasyPros ADP overlay used for draft timing. "
            "This never rewrites the immutable projection champion."
        )
    )
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--output-root", type=Path, default=Path("data/product/draft_market"))
    args = parser.parse_args()
    result = refresh_fantasypros_adp_snapshot(args.season, root=args.output_root)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
