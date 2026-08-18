from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.benchmark import (
    run_expanding_game_benchmark,
    v011_research_promotion_gate,
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


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def _markdown_report(
    candidate: dict[str, float],
    baseline: dict[str, float],
    opportunity_candidate: dict[str, float],
    opportunity_baseline: dict[str, float],
    promotion: dict[str, object],
) -> str:
    lines = [
        "# v0.11 Expanding Game Benchmark",
        "",
        "This report is research evidence only. No result changes the production champion automatically.",
        "",
        "## Game replay",
        "",
        "| Metric | Candidate | Baseline | Delta |",
        "|---|---:|---:|---:|",
    ]
    for metric in sorted(set(candidate) & set(baseline)):
        if metric.endswith("rows"):
            continue
        c = candidate[metric]
        b = baseline[metric]
        if isinstance(c, (int, float)) and isinstance(b, (int, float)):
            lines.append(f"| {metric} | {c:.6f} | {b:.6f} | {c - b:+.6f} |")
    lines.extend(
        [
            "",
            "## State-conditioned opportunity",
            "",
            "| Metric | Candidate | Static share | Delta |",
            "|---|---:|---:|---:|",
        ]
    )
    for metric in sorted(set(opportunity_candidate) & set(opportunity_baseline)):
        c = opportunity_candidate[metric]
        b = opportunity_baseline[metric]
        if isinstance(c, (int, float)) and isinstance(b, (int, float)):
            lines.append(f"| {metric} | {c:.6f} | {b:.6f} | {c - b:+.6f} |")
    lines.extend(
        [
            "",
            "## Promotion gate",
            "",
            f"Promoted: **{bool(promotion['promoted'])}**",
            "",
        ]
    )
    reasons = promotion.get("reasons") or []
    if reasons:
        lines.append("Reasons:")
        lines.extend(f"- {reason}" for reason in reasons)
    else:
        lines.append("All research gates cleared. Manual champion review is still required.")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the v0.11 expanding weekly game and opportunity benchmark."
    )
    parser.add_argument("--pbp", required=True)
    parser.add_argument("--schedules", required=True)
    parser.add_argument("--players")
    parser.add_argument("--player-actuals")
    parser.add_argument("--league-config", help="Optional LeagueConfig YAML for exact fantasy rescoring")
    parser.add_argument("--test-season", action="append", type=int, required=True)
    parser.add_argument("--week-start", type=int, default=1)
    parser.add_argument("--week-end", type=int, default=18)
    parser.add_argument("--simulations-per-game", type=int, default=100)
    parser.add_argument("--max-games-per-week", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--opportunity-prior-strength", type=float, default=12.0)
    parser.add_argument("--opportunity-half-life-weeks", type=float, default=4.0)
    parser.add_argument("--output-dir", default="artifacts/game_intelligence/v011")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    pbp = _read_table(args.pbp)
    schedules = _read_table(args.schedules)
    players = _read_table(args.players) if args.players else None
    player_actuals = _read_table(args.player_actuals) if args.player_actuals else None
    league_config = LeagueConfig.from_yaml(args.league_config) if args.league_config else None

    benchmark = run_expanding_game_benchmark(
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
    )
    decision = v011_research_promotion_gate(benchmark)

    benchmark.weekly_game_metrics.to_parquet(output / "weekly_game_metrics.parquet", index=False)
    benchmark.weekly_opportunity_metrics.to_parquet(
        output / "weekly_opportunity_metrics.parquet", index=False
    )
    payload: dict[str, object] = {
        "candidate_metrics": benchmark.candidate_metrics,
        "baseline_metrics": benchmark.baseline_metrics,
        "opportunity_candidate_metrics": benchmark.opportunity_candidate_metrics,
        "opportunity_baseline_metrics": benchmark.opportunity_baseline_metrics,
        "diagnostics": benchmark.diagnostics,
        "promotion": {
            "promoted": decision.promoted,
            "reasons": decision.reasons,
            "metrics": decision.metrics,
            "production_projection_changed": False,
        },
    }
    _write_json(output / "summary.json", payload)
    (output / "report.md").write_text(
        _markdown_report(
            benchmark.candidate_metrics,
            benchmark.baseline_metrics,
            benchmark.opportunity_candidate_metrics,
            benchmark.opportunity_baseline_metrics,
            payload["promotion"],
        )
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
