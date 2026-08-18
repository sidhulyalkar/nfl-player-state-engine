from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from player_state_engine.data.io import read_table, write_table
from player_state_engine.game_intelligence.evaluation import evaluate_play_call_probabilities
from player_state_engine.game_intelligence.models import PlayCallModel
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.tendencies import (
    attach_point_in_time_matchup_features,
    build_team_tendency_snapshots,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Frozen point-in-time play-call benchmark for the v0.10 research challenger."
    )
    parser.add_argument("--pbp", required=True)
    parser.add_argument("--test-season", type=int, required=True)
    parser.add_argument("--test-week-start", type=int, default=1)
    parser.add_argument("--output-dir", default="artifacts/reports/game_intelligence/play_call")
    args = parser.parse_args()

    raw = read_table(args.pbp)
    plays = build_play_intelligence_frame(raw)
    tendencies = build_team_tendency_snapshots(plays)
    data = attach_point_in_time_matchup_features(plays, tendencies)
    chronology = pd.to_numeric(data["season"], errors="coerce") * 25 + pd.to_numeric(
        data["week"], errors="coerce"
    )
    split = int(args.test_season) * 25 + int(args.test_week_start)
    train = data.loc[chronology < split].copy()
    test = data.loc[
        (pd.to_numeric(data["season"], errors="coerce") == int(args.test_season))
        & (pd.to_numeric(data["week"], errors="coerce") >= int(args.test_week_start))
    ].copy()
    if len(train) < 50 or test.empty:
        raise ValueError("Benchmark needs at least 50 training plays and a non-empty test set")

    model = PlayCallModel().fit(train)
    candidate_probability = model.predict_pass_probability(test)
    league_prior = float(train["is_dropback"].mean())
    baseline_probability = pd.to_numeric(
        test["pregame_pass_rate"], errors="coerce"
    ).fillna(league_prior)
    candidate = evaluate_play_call_probabilities(test["is_dropback"], candidate_probability)
    baseline = evaluate_play_call_probabilities(test["is_dropback"], baseline_probability)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions = test[
        [
            column
            for column in (
                "season",
                "week",
                "game_id",
                "play_id",
                "posteam",
                "defteam",
                "down",
                "ydstogo",
                "yardline_100",
                "score_differential",
                "is_dropback",
            )
            if column in test
        ]
    ].copy()
    predictions["candidate_pass_probability"] = candidate_probability
    predictions["baseline_pass_probability"] = baseline_probability.to_numpy(dtype=float)
    write_table(predictions, output_dir / "play_call_predictions.parquet")
    report = {
        "candidate": candidate,
        "baseline": baseline,
        "log_loss_delta": candidate["log_loss"] - baseline["log_loss"],
        "brier_delta": candidate["brier"] - baseline["brier"],
        "test_games": int(test["game_id"].nunique()),
        "research_only": True,
        "promotion": False,
        "promotion_reason": (
            "Play-call accuracy alone is insufficient. Full game/player opportunity replay is required."
        ),
    }
    report_path = output_dir / "metrics.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(report_path)


if __name__ == "__main__":
    main()
