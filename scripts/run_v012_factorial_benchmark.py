from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.factorial import (
    recommend_next_development,
    run_v012_factorial_benchmark,
    v012_state_opportunity_promotion_gate,
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
    assert isinstance(aggregates, dict)
    lines = [
        "# v0.12 Factorial Game Replay",
        "",
        "Research evidence only. No result automatically changes production projections.",
        "",
        "## Variants",
        "",
        "| Variant | Play call | Opportunity |",
        "|---|---|---|",
        "| profile_static | point-in-time profile | static usage share |",
        "| learned_static | learned play-call model | static usage share |",
        "| profile_state | point-in-time profile | state-conditioned allocator |",
        "| learned_state | learned play-call model | state-conditioned allocator |",
        "",
        "## Aggregate metrics",
        "",
    ]
    metrics = sorted(
        {
            key
            for variant in aggregates.values()
            if isinstance(variant, dict)
            for key in variant
            if key not in {"games", "player_rows", "fantasy_rows"}
        }
    )
    lines.append("| Metric | profile_static | learned_static | profile_state | learned_state |")
    lines.append("|---|---:|---:|---:|---:|")
    for metric in metrics:
        values = []
        for variant in ("profile_static", "learned_static", "profile_state", "learned_state"):
            record = aggregates.get(variant, {})
            value = record.get(metric) if isinstance(record, dict) else None
            values.append("" if value is None else f"{float(value):.6f}")
        lines.append(f"| {metric} | " + " | ".join(values) + " |")

    promotion = payload["promotion"]
    recommendation = payload["recommendation"]
    assert isinstance(promotion, dict)
    assert isinstance(recommendation, dict)
    lines.extend(
        [
            "",
            "## State-allocation promotion gate",
            "",
            f"Promoted to research generative champion: **{bool(promotion['promoted'])}**",
            "",
        ]
    )
    reasons = promotion.get("reasons") or []
    if reasons:
        lines.extend(f"- {reason}" for reason in reasons)
    lines.extend(
        [
            "",
            "## Next experiment router",
            "",
            f"Recommended track: **{recommendation.get('next_experiment')}**",
            "",
            str(recommendation.get("rationale", "")),
            "",
            "This router is comparative triage, not a promotion rule. Human review remains required.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the v0.12 four-variant expanding game replay and opportunity ablations."
    )
    parser.add_argument("--pbp", required=True)
    parser.add_argument("--schedules", required=True)
    parser.add_argument("--players")
    parser.add_argument("--player-actuals")
    parser.add_argument("--league-config")
    parser.add_argument("--test-season", action="append", type=int, required=True)
    parser.add_argument("--week-start", type=int, default=1)
    parser.add_argument("--week-end", type=int, default=18)
    parser.add_argument("--simulations-per-game", type=int, default=50)
    parser.add_argument("--max-games-per-week", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--opportunity-prior-strength", type=float, default=12.0)
    parser.add_argument("--opportunity-half-life-weeks", type=float, default=4.0)
    parser.add_argument("--skip-context-ablations", action="store_true")
    parser.add_argument("--output-dir", default="artifacts/game_intelligence/v012")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    pbp = _read_table(args.pbp)
    schedules = _read_table(args.schedules)
    players = _read_table(args.players) if args.players else None
    player_actuals = _read_table(args.player_actuals) if args.player_actuals else None
    league_config = LeagueConfig.from_yaml(args.league_config) if args.league_config else LeagueConfig()

    benchmark = run_v012_factorial_benchmark(
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
        run_context_ablations=not args.skip_context_ablations,
    )
    decision = v012_state_opportunity_promotion_gate(benchmark)
    recommendation = recommend_next_development(benchmark)
    benchmark.weekly_metrics.to_parquet(output / "weekly_factorial_metrics.parquet", index=False)
    benchmark.weekly_ablation_metrics.to_parquet(
        output / "weekly_opportunity_ablations.parquet", index=False
    )
    payload: dict[str, object] = {
        "aggregate_metrics": benchmark.aggregate_metrics,
        "aggregate_ablation_metrics": benchmark.aggregate_ablation_metrics,
        "diagnostics": benchmark.diagnostics,
        "promotion": {
            "promoted": decision.promoted,
            "reasons": decision.reasons,
            "metrics": decision.metrics,
            "production_projection_changed": False,
        },
        "recommendation": recommendation,
    }
    _json(output / "summary.json", payload)
    (output / "report.md").write_text(_report(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
