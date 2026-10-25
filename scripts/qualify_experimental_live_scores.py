#!/usr/bin/env python3
"""Local operator smoke test of explicitly opted-in experimental scoreboard.

Never stores/downloads raw provider JSON to disk; only prints normalized
game metadata and source freshness. The source has no approved rights.
"""
from __future__ import annotations

import argparse
import json

from player_state_engine.product.experimental_live_scores import live_score_pilot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument(
        "--require-live", action="store_true",
        help="Fail when no source-reported game is in progress.",
    )
    args = parser.parse_args()
    result = live_score_pilot(season=args.season, week=args.week)
    source = result["source"]
    print(json.dumps({
        "authority": result["authority"],
        "season": result["season"],
        "week": result["week"],
        "fetched_at_utc": source["fetched_at_utc"],
        "stale": source["stale"],
        "age_seconds": source["age_seconds"],
        "rights_status": source["rights_status"],
        "provider": source["name"],
        "games": [{
            "game_id": g["game_id"],
            "score": {
                g["away_team"]: g["away_score"],
                g["home_team"]: g["home_score"],
            },
            "state": g["state"],
            "period": g["period"],
            "clock": g["clock"],
            "provider_event_id": g["provider_event_id"],
        } for g in result["games"]],
    }, indent=2))
    if source["stale"]:
        parser.exit(2, "ERROR: source is stale; live qualification failed.\n")
    if args.require_live and not any(g["state"] == "in" for g in result["games"]):
        parser.exit(3, "ERROR: source reports no in-progress games.\n")
    print("Local scoreboard schema/freshness gate passed. Provider rights and live accuracy remain unverified.")


if __name__ == "__main__":
    main()
