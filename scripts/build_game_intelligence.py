from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd

from player_state_engine.data.io import read_table, write_table
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.tendencies import (
    attach_point_in_time_matchup_features,
    build_coaching_matchup_history,
    build_team_tendency_snapshots,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles


def _optional(path: str | None) -> pd.DataFrame | None:
    if not path:
        return None
    location = Path(path)
    return read_table(location) if location.exists() else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build v0.10 point-in-time play, tendency, usage and model artifacts."
    )
    parser.add_argument("--pbp", required=True)
    parser.add_argument("--participation")
    parser.add_argument("--charting")
    parser.add_argument("--players")
    parser.add_argument("--coaches")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--output-dir", default="artifacts/game_intelligence")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pbp = read_table(args.pbp)
    participation = _optional(args.participation)
    charting = _optional(args.charting)
    players = _optional(args.players)
    coaches = _optional(args.coaches)

    plays = build_play_intelligence_frame(pbp, participation=participation, charting=charting)
    tendencies = build_team_tendency_snapshots(plays)
    enriched = attach_point_in_time_matchup_features(plays, tendencies)
    usage = build_player_usage_profiles(
        plays,
        season=args.season,
        week=args.week,
        players=players,
    )
    chronology = pd.to_numeric(enriched["season"], errors="coerce") * 25 + pd.to_numeric(
        enriched["week"], errors="coerce"
    )
    cutoff = int(args.season) * 25 + int(args.week)
    train = enriched.loc[chronology < cutoff].copy()
    if len(train) < 50:
        raise ValueError("Need at least 50 pre-cutoff plays to fit game-intelligence models")

    play_call_model = PlayCallModel().fit(train)
    outcome_model = EmpiricalPlayOutcomeModel().fit(train)
    model_path = output_dir / "game_models.joblib"
    joblib.dump(
        {
            "play_call_model": play_call_model,
            "outcome_model": outcome_model,
            "feature_cutoff": {"season": args.season, "week": args.week},
            "model_source": "game_intelligence_v010_research",
            "promoted": False,
        },
        model_path,
    )

    paths = {
        "plays": str(write_table(plays, output_dir / "plays.parquet")),
        "tendencies": str(write_table(tendencies, output_dir / "team_tendencies.parquet")),
        "usage": str(write_table(usage, output_dir / "player_usage.parquet")),
        "model": str(model_path),
    }
    if coaches is not None:
        coach_history = build_coaching_matchup_history(plays, coaches)
        paths["coach_matchups"] = str(
            write_table(coach_history, output_dir / "coach_matchup_history.parquet")
        )
    metadata = {
        "season": args.season,
        "week": args.week,
        "training_plays": int(len(train)),
        "paths": paths,
        "promoted": False,
        "note": "Artifacts are research challengers until historical replay clears promotion gates.",
    }
    metadata_path = output_dir / "build_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(metadata_path)


if __name__ == "__main__":
    main()
