from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from player_state_engine.data.io import read_table, write_table
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import score_fantasy_stats
from player_state_engine.features.weekly import canonicalize_player_stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score one completed nflverse player-week snapshot under an exact LeagueConfig."
    )
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--league-config", type=Path, required=True)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw = read_table(args.stats)
    canonical = canonicalize_player_stats(raw)
    week = canonical.loc[
        canonical["season"].eq(args.season)
        & canonical["week"].eq(args.week)
        & canonical["position"].isin({"QB", "RB", "WR", "TE"})
    ].copy()
    if week.empty:
        raise ValueError(f"No skill-position actuals found for {args.season} week {args.week}.")
    if week["player_id"].duplicated().any():
        duplicate_ids = week.loc[week["player_id"].duplicated(keep=False), "player_id"].unique().tolist()
        raise ValueError(f"Expected one completed player-week row per player; duplicates: {duplicate_ids[:8]}")

    config = LeagueConfig.from_yaml(args.league_config)
    week["actual_points"] = score_fantasy_stats(week, config)
    output_columns = [
        "player_id",
        "player_name",
        "position",
        "recent_team",
        "season",
        "week",
        "actual_points",
    ]
    output = week[output_columns].sort_values(["position", "actual_points"], ascending=[True, False])
    write_table(output, args.output)
    print(args.output)
    print(f"scoring_contract_id={config.scoring_contract_id}")
    print(f"rows={len(output)}")


if __name__ == "__main__":
    main()
