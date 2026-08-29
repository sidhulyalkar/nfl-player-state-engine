from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from player_state_engine.config import load_config
from player_state_engine.data.io import read_table, write_table
from player_state_engine.data.nflverse import download_nflverse
from player_state_engine.evaluation.preseason import (
    PreseasonPromotionGate,
    run_preseason_season_benchmark,
)
from player_state_engine.fantasy.preseason import build_preseason_season_dataset
from player_state_engine.features.weekly import canonicalize_player_stats

TARGETS = ("fumbles_lost", "two_point_conversions")


def _attach_targets(dataset: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    raw = stats.copy()
    if "season_type" in raw:
        raw = raw.loc[raw["season_type"].astype(str).str.upper().eq("REG")].copy()
    canonical = canonicalize_player_stats(raw)
    for target in TARGETS:
        if target not in canonical:
            raise ValueError(f"nflverse player stats do not contain {target!r}")
        canonical[target] = pd.to_numeric(canonical[target], errors="coerce").fillna(0.0)
    totals = canonical.groupby(["season", "player_id"], as_index=False)[list(TARGETS)].sum()
    out = dataset.merge(totals, on=["season", "player_id"], how="left", validate="one_to_one")
    for target in TARGETS:
        out[target] = pd.to_numeric(out[target], errors="coerce").fillna(0.0)
        for lag in (1, 2):
            prior = out[["season", "player_id", target]].copy()
            prior["season"] = prior["season"] + lag
            prior = prior.rename(columns={target: f"prior{lag}_{target}"})
            out = out.merge(prior, on=["season", "player_id"], how="left", validate="one_to_one")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark fumbles-lost and two-point preseason distributions separately."
    )
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--seasons", nargs="+", type=int, default=list(range(2015, 2026)))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/preseason_minor_scoring"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    paths = download_nflverse(args.seasons, args.raw_dir)
    stats = read_table(paths["player_stats"])
    rosters = read_table(paths["rosters_weekly"])
    players = read_table(paths["players"])
    base, diagnostics = build_preseason_season_dataset(
        stats,
        rosters,
        players=players,
        seasons=args.seasons,
        snapshot_week=1,
    )
    dataset = _attach_targets(base, stats)

    config = load_config(args.config)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    write_table(dataset, output / "dataset.parquet")

    decisions: dict[str, object] = {}
    comparisons: list[pd.DataFrame] = []
    for target in TARGETS:
        model_config = replace(config.model, targets=(target,))
        gate = PreseasonPromotionGate(
            primary_target=target,
            min_primary_pinball_improvement_pct=0.0,
            max_component_pinball_regression_pct=0.0,
            min_primary_season_win_rate=0.50,
            max_primary_position_regression_pct=5.0,
            max_primary_rookie_regression_pct=10.0,
            min_rookie_rows=75,
            bootstrap_samples=5000,
            random_state=42,
            require_positive_season_bootstrap_ci=False,
        )
        result = run_preseason_season_benchmark(
            dataset,
            model_config=model_config,
            targets=(target,),
            min_train_seasons=4,
            gate_policy=gate,
        )
        decisions[target] = result.gate.as_dict()
        comparison = result.comparisons.copy()
        comparison["target"] = target
        comparisons.append(comparison)
        write_table(result.predictions, output / f"{target}_predictions.parquet")
        write_table(result.season_metrics, output / f"{target}_season_metrics.csv")
        write_table(result.position_metrics, output / f"{target}_position_metrics.csv")
        write_table(result.rookie_metrics, output / f"{target}_rookie_metrics.csv")

    write_table(pd.concat(comparisons, ignore_index=True), output / "comparisons.csv")
    manifest = {
        "schema_version": 1,
        "authority": "supplemental_scoring_research_only",
        "automatic_promotion": False,
        "targets": list(TARGETS),
        "dataset_diagnostics": diagnostics.as_dict(),
        "decisions": decisions,
        "policy_note": (
            "These post-primary supplemental gates were frozen before results. A failed learned "
            "target may fall back to the historically stronger baseline, but cannot be relabelled "
            "as a qualified quantile-engine target."
        ),
    }
    (output / "qualification.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
