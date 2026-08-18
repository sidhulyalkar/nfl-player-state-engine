from __future__ import annotations

import argparse
from pathlib import Path

from player_state_engine.integrations.portfolio import LeaguePortfolio


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync every configured Sleeper/ESPN fantasy league.")
    parser.add_argument("--config", type=Path, default=Path("configs/fantasy/leagues.yaml"))
    parser.add_argument("--no-free-agents", action="store_true")
    args = parser.parse_args()

    portfolio = LeaguePortfolio.from_yaml(args.config)
    paths = portfolio.sync(include_free_agents=not args.no_free_agents)
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
