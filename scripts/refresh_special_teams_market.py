from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.product.special_teams_refresh import refresh_special_teams_market


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh external-market-only kicker and DST redraft guidance from maintained "
            "ffverse/nflverse sources. No model projections or VORP are created."
        )
    )
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/product/special_teams_market/current.json"),
    )
    args = parser.parse_args()

    result = refresh_special_teams_market(int(args.season), output=args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
