from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from player_state_engine.config import load_config
from player_state_engine.data.io import read_table, write_table
from player_state_engine.data.nflverse import download_nflverse
from player_state_engine.evaluation.preseason import (
    PreseasonPromotionGate,
    run_preseason_season_benchmark,
)
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.preseason import build_preseason_season_dataset
from player_state_engine.fantasy.preseason_league_score import (
    LEAGUE_SCORE_TARGET,
    build_preseason_league_scored_dataset,
)

DEFAULT_LEAGUES = (
    "configs/fantasy/8_team_ppr_2qb_expanded.yaml",
    "configs/fantasy/12_team_half_ppr_median.yaml",
)


def _slug(path: Path) -> str:
    return path.stem.replace(" ", "_")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark direct preseason fantasy-score distributions after scoring historical "
            "outcomes under each exact league contract."
        )
    )
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--league", action="append", default=[])
    parser.add_argument("--seasons", nargs="+", type=int, default=list(range(2015, 2026)))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/direct_league_score"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    league_paths = tuple(Path(value) for value in (args.league or DEFAULT_LEAGUES))
    if not league_paths:
        raise ValueError("At least one league contract is required")

    paths = download_nflverse(args.seasons, args.raw_dir)
    stats = read_table(paths["player_stats"])
    rosters = read_table(paths["rosters_weekly"])
    players = read_table(paths["players"])
    base, base_diagnostics = build_preseason_season_dataset(
        stats,
        rosters,
        players=players,
        seasons=args.seasons,
        snapshot_week=1,
    )
    base_config = load_config(args.config)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)

    policy = PreseasonPromotionGate(
        primary_target=LEAGUE_SCORE_TARGET,
        min_primary_pinball_improvement_pct=1.0,
        max_component_pinball_regression_pct=0.0,
        min_primary_season_win_rate=0.60,
        max_primary_position_regression_pct=3.0,
        max_primary_rookie_regression_pct=5.0,
        min_rookie_rows=75,
        bootstrap_samples=5000,
        random_state=42,
        require_positive_season_bootstrap_ci=True,
    )

    league_results: dict[str, object] = {}
    for league_path in league_paths:
        league = LeagueConfig.from_yaml(league_path)
        slug = _slug(league_path)
        league_output = output / slug
        league_output.mkdir(parents=True, exist_ok=True)
        dataset, target_diagnostics = build_preseason_league_scored_dataset(
            base,
            stats,
            league,
            target=LEAGUE_SCORE_TARGET,
        )

        # Source-audit canonical PPR against the maintained nflverse PPR field before treating the
        # direct PPR target as a scoring-equivalent outcome. This is not a promotion threshold.
        if league.scoring.lower() == "ppr":
            if target_diagnostics.ppr_reference_rows <= 0:
                raise RuntimeError("Canonical PPR source consistency check has no comparable rows")
            if (
                target_diagnostics.ppr_reference_max_abs_error is None
                or target_diagnostics.ppr_reference_max_abs_error > 1e-9
            ):
                raise RuntimeError(
                    "Reconstructed canonical PPR does not match nflverse fantasy_points_ppr; "
                    f"max_abs_error={target_diagnostics.ppr_reference_max_abs_error}"
                )

        model_config = replace(base_config.model, targets=(LEAGUE_SCORE_TARGET,))
        result = run_preseason_season_benchmark(
            dataset,
            model_config=model_config,
            targets=(LEAGUE_SCORE_TARGET,),
            min_train_seasons=4,
            gate_policy=policy,
        )
        write_table(dataset, league_output / "dataset.parquet")
        write_table(result.predictions, league_output / "predictions.parquet")
        write_table(result.summary_metrics, league_output / "summary_metrics.csv")
        write_table(result.season_metrics, league_output / "season_metrics.csv")
        write_table(result.position_metrics, league_output / "position_metrics.csv")
        write_table(result.rookie_metrics, league_output / "rookie_metrics.csv")
        write_table(result.comparisons, league_output / "comparisons.csv")
        league_results[slug] = {
            "league_path": str(league_path),
            "teams": int(league.teams),
            "scoring": league.scoring,
            "median_scoring": bool(league.median_scoring),
            "median_scoring_in_target": False,
            "target_diagnostics": target_diagnostics.as_dict(),
            "gate": result.gate.as_dict(),
        }

    manifest = {
        "schema_version": 1,
        "authority": "direct_league_score_research_only",
        "automatic_promotion": False,
        "seasons": [int(value) for value in args.seasons],
        "target": LEAGUE_SCORE_TARGET,
        "population_contract": "opening_roster_universe_with_zero_output_seasons",
        "scoring_contract": "historical_outcomes_scored_before_quantile_model_fit",
        "median_policy_contract": (
            "median-game scoring is not represented by the player-season target and remains a "
            "separate team-week policy qualification"
        ),
        "base_dataset_diagnostics": base_diagnostics.as_dict(),
        "preregistered_gate": {
            "min_primary_pinball_improvement_pct": 1.0,
            "min_primary_season_win_rate": 0.60,
            "max_primary_position_regression_pct": 3.0,
            "max_primary_rookie_regression_pct": 5.0,
            "bootstrap_samples": 5000,
            "require_positive_season_bootstrap_ci": True,
        },
        "leagues": league_results,
    }
    (output / "qualification.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
