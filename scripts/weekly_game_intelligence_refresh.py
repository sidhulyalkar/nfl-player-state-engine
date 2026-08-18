from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import joblib
import pandas as pd

from player_state_engine.data.io import read_table, write_table
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.continual import (
    append_game_intelligence_registry,
    build_game_intelligence_manifest,
)
from player_state_engine.game_intelligence.evaluation import game_simulation_promotion_gate
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.replay import frozen_game_replay
from player_state_engine.game_intelligence.tendencies import (
    attach_point_in_time_matchup_features,
    build_team_tendency_snapshots,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _latest_completed_week(pbp: pd.DataFrame, season: int) -> int:
    weeks = pd.to_numeric(
        pbp.loc[pd.to_numeric(pbp["season"], errors="coerce") == int(season), "week"],
        errors="coerce",
    ).dropna()
    if weeks.empty:
        raise ValueError(f"No completed PBP found for season {season}")
    return int(weeks.max())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a point-in-time weekly game-intelligence challenger and replay gate."
    )
    parser.add_argument("--pbp", required=True)
    parser.add_argument("--schedules", required=True)
    parser.add_argument("--players")
    parser.add_argument("--player-actuals")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--completed-week", type=int)
    parser.add_argument("--replay-weeks", type=int, default=4)
    parser.add_argument("--simulations-per-game", type=int, default=150)
    parser.add_argument("--output-root", default="artifacts/game_intelligence/weekly")
    parser.add_argument(
        "--registry", default="artifacts/models/game_intelligence/registry.json"
    )
    args = parser.parse_args()

    pbp_path = Path(args.pbp)
    schedules_path = Path(args.schedules)
    pbp = read_table(pbp_path)
    schedules = read_table(schedules_path)
    players = read_table(args.players) if args.players else None
    player_actuals = read_table(args.player_actuals) if args.player_actuals else None
    completed_week = args.completed_week or _latest_completed_week(pbp, args.season)
    next_week = completed_week + 1
    replay_start = max(1, completed_week - max(1, args.replay_weeks) + 1)

    plays = build_play_intelligence_frame(pbp)
    tendencies = build_team_tendency_snapshots(plays)
    enriched = attach_point_in_time_matchup_features(plays, tendencies)
    cutoff = int(args.season) * 25 + int(next_week)
    chronology = pd.to_numeric(enriched["season"], errors="coerce") * 25 + pd.to_numeric(
        enriched["week"], errors="coerce"
    )
    train = enriched.loc[chronology < cutoff].copy()
    play_call_model = PlayCallModel().fit(train)
    outcome_model = EmpiricalPlayOutcomeModel().fit(train)
    usage = build_player_usage_profiles(
        plays,
        season=args.season,
        week=next_week,
        players=players,
    )

    output_root = Path(args.output_root) / f"{args.season}_w{completed_week:02d}"
    output_root.mkdir(parents=True, exist_ok=True)
    write_table(tendencies, output_root / "team_tendencies.parquet")
    write_table(usage, output_root / "player_usage_next_week.parquet")
    model_path = output_root / "game_models.joblib"
    joblib.dump(
        {
            "play_call_model": play_call_model,
            "outcome_model": outcome_model,
            "feature_cutoff": {"season": args.season, "week": next_week},
            "promoted": False,
        },
        model_path,
    )

    replay = frozen_game_replay(
        pbp,
        schedules,
        test_season=args.season,
        test_week_start=replay_start,
        test_week_end=completed_week,
        players=players,
        player_actuals=player_actuals,
        league_config=LeagueConfig(scoring="ppr"),
        simulations_per_game=args.simulations_per_game,
    )
    decision = game_simulation_promotion_gate(
        replay.candidate_metrics,
        replay.baseline_metrics,
    )
    report = {
        "candidate": replay.candidate_metrics,
        "baseline": replay.baseline_metrics,
        "promotion_gate": decision.to_dict(),
        "diagnostics": replay.diagnostics,
        "next_prediction_week": next_week,
        "automatic_promotion": False,
    }
    report_path = output_root / "weekly_replay.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    data_paths: dict[str, Path] = {"pbp": pbp_path, "schedules": schedules_path}
    if args.players:
        data_paths["players"] = Path(args.players)
    if args.player_actuals:
        data_paths["player_actuals"] = Path(args.player_actuals)
    manifest = build_game_intelligence_manifest(
        model_id=f"game-intelligence-{args.season}-w{completed_week:02d}",
        feature_cutoff=f"{args.season}-W{next_week:02d}",
        code_version=_git_sha(),
        data_paths=data_paths,
        metrics=replay.candidate_metrics,
        promoted=decision.promoted,
        promotion_reasons=decision.reasons,
        evidence_tiers={
            "pbp": "live",
            "schedules": "live",
            "players": "live_fail_soft",
            "player_actuals": "completed_game_outcomes",
        },
        notes=[
            "Promotion gate result is recorded for research governance only.",
            "This script never changes the production champion automatically.",
        ],
    )
    registry_path = append_game_intelligence_registry(args.registry, manifest)
    print(report_path)
    print(model_path)
    print(registry_path)


if __name__ == "__main__":
    main()
