from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from player_state_engine.config import ModelConfig
from player_state_engine.evaluation.benchmark import BenchmarkResult, run_multiseason_benchmark
from player_state_engine.evaluation.reporting import persist_benchmark

FEATURE_FAMILIES: dict[str, tuple[str, ...]] = {
    "official_availability": ("availability_",),
    "objective_opportunity": (
        "opportunity_",
        "is_rookie_prior",
        "team_changed_prior",
        "quarterback_changed_prior",
        "ol_continuity",
    ),
    "news": ("news_",),
    "public_context": ("persona_",),
}


@dataclass(slots=True)
class AblationRun:
    name: str
    feature_count: int
    result: BenchmarkResult
    artifact_paths: dict[str, Path] | None = None


def _matches_family(column: str, family: str) -> bool:
    prefixes = FEATURE_FAMILIES[family]
    return any(column.startswith(prefix) or column == prefix for prefix in prefixes)


def build_ablation_feature_sets(
    base_features: Iterable[str], frame: pd.DataFrame
) -> dict[str, list[str]]:
    base = list(dict.fromkeys(base_features))
    available = list(frame.columns)
    family_columns = {
        family: [column for column in available if _matches_family(column, family)]
        for family in FEATURE_FAMILIES
    }

    variants: dict[str, list[str]] = {"numerical_baseline": base}
    variants["official_availability_only"] = list(
        dict.fromkeys([*base, *family_columns["official_availability"]])
    )
    variants["objective_opportunity_only"] = list(
        dict.fromkeys([*base, *family_columns["objective_opportunity"]])
    )
    variants["news_only"] = list(dict.fromkeys([*base, *family_columns["news"]]))
    variants["public_context_only"] = list(
        dict.fromkeys([*base, *family_columns["public_context"]])
    )
    variants["combined_approved_intelligence"] = list(
        dict.fromkeys(
            [
                *base,
                *family_columns["official_availability"],
                *family_columns["objective_opportunity"],
                *family_columns["news"],
                *family_columns["public_context"],
            ]
        )
    )
    return variants


def make_shuffled_player_control(
    frame: pd.DataFrame,
    *,
    prefixes: tuple[str, ...] = ("availability_", "news_", "persona_"),
    seed: int = 42,
) -> pd.DataFrame:
    """Shuffle intelligence between players within season/week/position strata."""

    output = frame.copy()
    columns = [column for column in output if column.startswith(prefixes)]
    if not columns:
        return output
    rng = np.random.default_rng(seed)
    strata = [column for column in ("season", "week", "position") if column in output]
    if not strata:
        permutation = rng.permutation(len(output))
        output[columns] = output.iloc[permutation][columns].to_numpy()
        return output
    for _, index in output.groupby(strata, dropna=False).groups.items():
        index = np.asarray(list(index))
        if len(index) < 2:
            continue
        permutation = rng.permutation(index)
        output.loc[index, columns] = output.loc[permutation, columns].to_numpy()
    return output


def make_shifted_time_control(
    frame: pd.DataFrame,
    *,
    prefixes: tuple[str, ...] = ("availability_", "news_", "persona_"),
    periods: int = -1,
) -> pd.DataFrame:
    """Intentionally shift intelligence across time as a leakage sensitivity test.

    The default ``periods=-1`` moves a player's next observed intelligence into
    the current row. This control is never promotion-eligible; unexpectedly
    large gains indicate that timestamp leakage could dominate the experiment.
    """

    output = frame.sort_values(["player_id", "season", "week"]).copy()
    columns = [column for column in output if column.startswith(prefixes)]
    if columns:
        output[columns] = output.groupby("player_id", sort=False)[columns].shift(periods)
    return output.sort_index()


def run_intelligence_ablation_benchmark(
    frame: pd.DataFrame,
    base_features: Iterable[str],
    target: str,
    config: ModelConfig,
    *,
    output_dir: str | Path | None = None,
    min_train_weeks: int = 24,
    retrain_every_weeks: int = 4,
    rolling_window: int = 5,
    seed: int = 42,
) -> dict[str, AblationRun]:
    variants = build_ablation_feature_sets(base_features, frame)
    control_frames = {
        "shuffled_player_control": make_shuffled_player_control(frame, seed=seed),
        "shifted_time_leakage_control": make_shifted_time_control(frame),
    }
    variants["shuffled_player_control"] = variants["combined_approved_intelligence"]
    variants["shifted_time_leakage_control"] = variants["combined_approved_intelligence"]

    runs: dict[str, AblationRun] = {}
    for name, features in variants.items():
        working = control_frames.get(name, frame)
        result = run_multiseason_benchmark(
            working,
            features,
            target,
            config=config,
            min_train_weeks=min_train_weeks,
            retrain_every_weeks=retrain_every_weeks,
            rolling_window=rolling_window,
        )
        paths = None
        if output_dir is not None:
            paths = persist_benchmark(result, target, Path(output_dir) / name)
        runs[name] = AblationRun(
            name=name, feature_count=len(features), result=result, artifact_paths=paths
        )
    return runs


def summarize_ablation_runs(runs: dict[str, AblationRun]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for name, run in runs.items():
        engine = run.result.summary_metrics.loc[
            run.result.summary_metrics["method"] == "quantile_engine"
        ]
        if engine.empty:
            continue
        row = engine.iloc[0].to_dict()
        row.update({"ablation": name, "feature_count": run.feature_count})
        rows.append(row)
    output = pd.DataFrame(rows)
    if output.empty:
        return output
    baseline = output.loc[output["ablation"] == "numerical_baseline", "mean_pinball"]
    baseline_value = float(baseline.iloc[0]) if not baseline.empty else np.nan
    output["pinball_improvement_vs_numerical_pct"] = (
        100.0 * (baseline_value - output["mean_pinball"]) / max(baseline_value, 1e-12)
    )
    return output.sort_values("mean_pinball").reset_index(drop=True)
