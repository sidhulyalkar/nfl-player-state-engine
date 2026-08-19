from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.decision_benchmark import (
    recommend_v016_development,
    run_v015_decision_benchmark,
    v015_decision_promotion_gate,
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

    comparison = ("transition_legacy_decision", "transition_decision")
    lines = [
        "# v0.15 Fourth-Down Decision & Drive-Termination Replay",
        "",
        "Research evidence only. No result automatically changes production projections.",
        "",
        "## Primary full-simulation comparison",
        "",
        "| Metric | transition_legacy_decision | transition_decision |",
        "|---|---:|---:|",
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
    }
    metrics = sorted(
        {
            key
            for variant in comparison
            for key in (
                aggregates.get(variant, {})
                if isinstance(aggregates.get(variant, {}), dict)
                else {}
            )
            if key not in excluded
        }
    )
    for metric in metrics:
        values: list[str] = []
        for variant in comparison:
            record = aggregates.get(variant, {})
            value = record.get(metric) if isinstance(record, dict) else None
            values.append("" if value is None else f"{float(value):.6f}")
        lines.append(f"| {metric} | " + " | ".join(values) + " |")

    lines.extend(
        [
            "",
            "## Isolated decision and termination diagnostics",
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
            "## v0.15 research gate",
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
            "## v0.16 evidence router",
            "",
            f"Recommended track: **{recommendation.get('next_experiment')}**",
            "",
            str(recommendation.get("rationale", "")),
            "",
            "The termination hazard remains diagnostic-only in v0.15. Human review is required, and the live simulation endpoint remains unchanged.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the v0.15 fourth-down decision expanding frozen replay."
    )
    parser.add_argument("--pbp", required=True)
    parser.add_argument("--schedules", required=True)
    parser.add_argument("--players")
    parser.add_argument("--player-actuals")
    parser.add_argument("--league-config")
    parser.add_argument("--test-season", action="append", type=int, required=True)
    parser.add_argument("--week-start", type=int, default=1)
    parser.add_argument("--week-end", type=int, default=18)
    parser.add_argument("--simulations-per-game", type=int, default=15)
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
    parser.add_argument("--termination-prior-strength", type=float, default=36.0)
    parser.add_argument("--termination-half-life-weeks", type=float, default=8.0)
    parser.add_argument("--output-dir", default="artifacts/game_intelligence/v015")
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

    benchmark = run_v015_decision_benchmark(
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
        termination_prior_strength=args.termination_prior_strength,
        termination_half_life_weeks=args.termination_half_life_weeks,
    )
    decision = v015_decision_promotion_gate(benchmark)
    recommendation = recommend_v016_development(benchmark)

    benchmark.weekly_metrics.to_parquet(
        output / "weekly_decision_factorial_metrics.parquet", index=False
    )
    benchmark.weekly_isolated_metrics.to_parquet(
        output / "weekly_decision_isolated_metrics.parquet", index=False
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
