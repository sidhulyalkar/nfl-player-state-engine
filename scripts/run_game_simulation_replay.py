from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.data.io import read_table, write_table
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.evaluation import game_simulation_promotion_gate
from player_state_engine.game_intelligence.replay import frozen_game_replay


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run frozen multi-game replay for the v0.10 play-by-play simulator."
    )
    parser.add_argument("--pbp", required=True)
    parser.add_argument("--schedules", required=True)
    parser.add_argument("--players")
    parser.add_argument("--player-actuals")
    parser.add_argument("--test-season", type=int, required=True)
    parser.add_argument("--test-week-start", type=int, default=1)
    parser.add_argument("--test-week-end", type=int, default=18)
    parser.add_argument("--simulations-per-game", type=int, default=250)
    parser.add_argument("--max-games", type=int)
    parser.add_argument("--scoring", choices=["standard", "half_ppr", "ppr"], default="ppr")
    parser.add_argument("--output-dir", default="artifacts/reports/game_intelligence/replay")
    args = parser.parse_args()

    pbp = read_table(args.pbp)
    schedules = read_table(args.schedules)
    players = read_table(args.players) if args.players else None
    player_actuals = read_table(args.player_actuals) if args.player_actuals else None
    league = LeagueConfig(scoring=args.scoring)
    replay = frozen_game_replay(
        pbp,
        schedules,
        test_season=args.test_season,
        test_week_start=args.test_week_start,
        test_week_end=args.test_week_end,
        players=players,
        player_actuals=player_actuals,
        league_config=league,
        simulations_per_game=args.simulations_per_game,
        max_games=args.max_games,
    )
    decision = game_simulation_promotion_gate(
        replay.candidate_metrics,
        replay.baseline_metrics,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_table(replay.candidate_team_draws, output_dir / "candidate_team_draws.parquet")
    write_table(replay.baseline_team_draws, output_dir / "baseline_team_draws.parquet")
    write_table(
        replay.candidate_player_predictions,
        output_dir / "candidate_player_predictions.parquet",
    )
    write_table(
        replay.baseline_player_predictions,
        output_dir / "baseline_player_predictions.parquet",
    )
    write_table(replay.observed_teams, output_dir / "observed_teams.parquet")
    write_table(replay.observed_opportunity, output_dir / "observed_opportunity.parquet")
    report = {
        "candidate": replay.candidate_metrics,
        "baseline": replay.baseline_metrics,
        "diagnostics": replay.diagnostics,
        "promotion_gate": decision.to_dict(),
        "research_only": True,
        "production_projection_changed": False,
    }
    report_path = output_dir / "replay_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(report_path)


if __name__ == "__main__":
    main()
