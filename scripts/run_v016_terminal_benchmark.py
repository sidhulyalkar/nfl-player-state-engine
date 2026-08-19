from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.terminal_benchmark import (
    recommend_v017_development,
    run_v016_terminal_benchmark,
    v016_terminal_promotion_gate,
)

_PARENT_COMPARISONS = (
    (
        "legacy_transition_legacy_decision_legacy_terminal",
        "legacy_transition_legacy_decision_terminal",
    ),
    (
        "legacy_transition_decision_legacy_terminal",
        "legacy_transition_decision_terminal",
    ),
    (
        "transition_legacy_decision_legacy_terminal",
        "transition_legacy_decision_terminal",
    ),
    (
        "transition_decision_legacy_terminal",
        "transition_decision_terminal",
    ),
)


def _read_table(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(source)
    if suffix in {".csv", ".gz"}:
        return pd.read_csv(source)
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(source, lines=suffix == ".jsonl")
    raise ValueError(f"Unsupported table format: {source}")


def _json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def _report(payload: dict[str, object]) -> str:
    aggregates = payload["aggregate_metrics"]
    isolated = payload["aggregate_isolated_metrics"]
    promotion = payload["promotion"]
    recommendation = payload["recommendation"]
    assert isinstance(aggregates, dict)
    assert isinstance(isolated, dict)
    assert isinstance(promotion, dict)
    assert isinstance(recommendation, dict)

    lines = [
        "# v0.16 Terminal-Family Generation Replay",
        "",
        "Research evidence only. No result automatically changes production projections.",
        "",
        "## Terminal authority across parent world-model contexts",
        "",
        "Each pair changes only terminal-family authority. Transition and fourth-down decision authority remain fixed within the pair.",
        "",
    ]
    excluded = {
        "games",
        "player_rows",
        "predicted_player_rows",
        "observed_player_rows",
        "fantasy_rows",
        "drive_team_rows",
        "transition_team_rows",
        "decision_team_rows",
        "terminal_team_rows",
    }
    focus = (
        "team_terminal_non_clock_events_mae",
        "team_terminal_score_events_mae",
        "team_terminal_turnover_events_mae",
        "team_terminal_downs_events_mae",
        "team_plays_mae",
        "team_drives_mae",
        "team_points_mae",
        "player_opportunity_mae",
        "fantasy_pinball_loss",
        "terminal_conditioning_fallback_rate",
    )
    for baseline, candidate in _PARENT_COMPARISONS:
        lines.extend(
            [
                f"### `{candidate}` vs `{baseline}`",
                "",
                "| Metric | Baseline | Terminal authority | Delta |",
                "|---|---:|---:|---:|",
            ]
        )
        baseline_record = aggregates.get(baseline, {})
        candidate_record = aggregates.get(candidate, {})
        if not isinstance(baseline_record, dict):
            baseline_record = {}
        if not isinstance(candidate_record, dict):
            candidate_record = {}
        metrics = [
            metric
            for metric in focus
            if metric not in excluded
            and metric in baseline_record
            and metric in candidate_record
        ]
        for metric in metrics:
            b = float(baseline_record[metric])
            c = float(candidate_record[metric])
            lines.append(f"| {metric} | {b:.6f} | {c:.6f} | {c - b:+.6f} |")
        lines.append("")

    lines.extend(
        [
            "## Isolated terminal-family diagnostics",
            "",
            "| Metric | Value |",
            "|---|---:|",
        ]
    )
    for metric, value in sorted(isolated.items()):
        lines.append(f"| {metric} | {float(value):.6f} |")

    lines.extend(
        [
            "",
            "## v0.16 research gate",
            "",
            f"Eligible for manual research-champion review: **{bool(promotion.get('promoted'))}**",
            "",
        ]
    )
    reasons = promotion.get("reasons") or []
    if reasons:
        lines.extend(f"- {reason}" for reason in reasons)

    lines.extend(
        [
            "",
            "## v0.17 evidence router",
            "",
            f"Recommended track: **{recommendation.get('next_experiment')}**",
            "",
            str(recommendation.get("rationale", "")),
            "",
            "The live simulation endpoint remains on the established non-terminal-authority path. Human review remains required.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the v0.16 terminal-family eight-cell expanding frozen replay."
    )
    parser.add_argument("--pbp", required=True)
    parser.add_argument("--schedules", required=True)
    parser.add_argument("--players")
    parser.add_argument("--player-actuals")
    parser.add_argument("--league-config")
    parser.add_argument("--test-season", action="append", type=int, required=True)
    parser.add_argument("--week-start", type=int, default=1)
    parser.add_argument("--week-end", type=int, default=18)
    parser.add_argument("--simulations-per-game", type=int, default=8)
    parser.add_argument("--max-games-per-week", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--opportunity-prior-strength", type=float, default=12.0)
    parser.add_argument("--opportunity-half-life-weeks", type=float, default=4.0)
    parser.add_argument("--drive-prior-strength", type=float, default=24.0)
    parser.add_argument("--drive-half-life-weeks", type=float, default=6.0)
    parser.add_argument("--transition-prior-strength", type=float, default=18.0)
    parser.add_argument("--transition-half-life-weeks", type=float, default=8.0)
    parser.add_argument("--decision-prior-strength", type=float, default=24.0)
    parser.add_argument("--decision-half-life-weeks", type=float, default=8.0)
    parser.add_argument("--terminal-prior-strength", type=float, default=30.0)
    parser.add_argument("--terminal-half-life-weeks", type=float, default=8.0)
    parser.add_argument("--output-dir", default="artifacts/game_intelligence/v016")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    pbp = _read_table(args.pbp)
    schedules = _read_table(args.schedules)
    players = _read_table(args.players) if args.players else None
    player_actuals = _read_table(args.player_actuals) if args.player_actuals else None
    league_config = (
        LeagueConfig.from_yaml(args.league_config)
        if args.league_config
        else LeagueConfig()
    )

    benchmark = run_v016_terminal_benchmark(
        pbp,
        schedules,
        test_seasons=tuple(args.test_season),
        week_start=args.week_start,
        week_end=args.week_end,
        players=players,
        player_actuals=player_actuals,
        league_config=league_config,
        simulations_per_game=args.simulations_per_game,
        max_games_per_week=args.max_games_per_week,
        seed=args.seed,
        opportunity_prior_strength=args.opportunity_prior_strength,
        opportunity_half_life_weeks=args.opportunity_half_life_weeks,
        drive_prior_strength=args.drive_prior_strength,
        drive_half_life_weeks=args.drive_half_life_weeks,
        transition_prior_strength=args.transition_prior_strength,
        transition_half_life_weeks=args.transition_half_life_weeks,
        decision_prior_strength=args.decision_prior_strength,
        decision_half_life_weeks=args.decision_half_life_weeks,
        terminal_prior_strength=args.terminal_prior_strength,
        terminal_half_life_weeks=args.terminal_half_life_weeks,
    )
    decision = v016_terminal_promotion_gate(benchmark)
    recommendation = recommend_v017_development(benchmark)

    benchmark.weekly_metrics.to_parquet(
        output / "weekly_terminal_factorial_metrics.parquet", index=False
    )
    benchmark.weekly_isolated_metrics.to_parquet(
        output / "weekly_terminal_isolated_metrics.parquet", index=False
    )
    payload: dict[str, object] = {
        "aggregate_metrics": benchmark.aggregate_metrics,
        "aggregate_isolated_metrics": benchmark.aggregate_isolated_metrics,
        "diagnostics": benchmark.diagnostics,
        "promotion": {
            "promoted": decision.promoted,
            "reasons": decision.reasons,
            "metrics": decision.metrics,
            "research_champion_only": True,
            "automatic_promotion": False,
            "production_projection_changed": False,
        },
        "recommendation": recommendation,
    }
    _json(output / "summary.json", payload)
    (output / "report.md").write_text(_report(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
