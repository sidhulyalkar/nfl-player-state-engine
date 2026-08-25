from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from player_state_engine.config import ModelConfig
from player_state_engine.evaluation.ablations import AblationRun
from player_state_engine.evaluation.benchmark import run_multiseason_benchmark
from player_state_engine.evaluation.reporting import persist_benchmark
from player_state_engine.state_graph.experiments import benjamini_hochberg, consistency_rate

_FAMILY_PREFIXES: dict[str, tuple[str, ...]] = {
    "official_availability": ("availability_", "official_structured_"),
    "objective_opportunity": ("opportunity_",),
    "structured_news": ("news_", "news_structured_"),
    "public_player_context": ("persona_",),
}
_OBJECTIVE_EXACT = {
    "is_rookie_prior",
    "team_changed_prior",
    "quarterback_changed_prior",
    "ol_continuity",
}
_NON_MODEL_SUFFIXES = ("_as_of_utc", "_source_covered", "_research_only")
_SOURCE_COVERAGE_COLUMNS: dict[str, tuple[str, ...]] = {
    "official_availability": (
        "official_availability_source_covered",
        "official_structured_source_covered",
    ),
    "objective_opportunity": ("objective_opportunity_source_covered",),
    "structured_news": (
        "structured_news_source_covered",
        "news_structured_source_covered",
    ),
    "public_player_context": (
        "public_player_context_source_covered",
        "persona_source_covered",
    ),
}
_PREVALENCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "official_availability": (
        "official_structured_snapshot_found",
        "availability_snapshot_found",
    ),
    "objective_opportunity": ("objective_opportunity_snapshot_found",),
    "structured_news": ("news_structured_snapshot_found", "news_snapshot_found"),
    "public_player_context": ("persona_snapshot_found",),
}
_CONFLICT_COLUMNS: dict[str, tuple[str, ...]] = {
    "official_availability": ("official_structured_max_conflict",),
    "objective_opportunity": (),
    "structured_news": ("news_structured_max_conflict",),
    "public_player_context": (),
}
_CANDIDATE_SEQUENCE: tuple[tuple[str, str, str], ...] = (
    ("official_availability", "numerical_baseline", "official_availability"),
    ("objective_opportunity", "official_availability", "objective_reference"),
    ("structured_news", "objective_reference", "structured_news"),
    ("public_player_context", "structured_news", "public_player_context"),
)


@dataclass(slots=True, frozen=True)
class BootstrapEvidence:
    effect: float
    ci_low: float
    ci_high: float
    probability_improves: float
    p_value: float
    blocks: int
    bootstrap_samples: int


@dataclass(slots=True)
class IntelligenceEvidenceRun:
    runs: dict[str, AblationRun]
    evidence: pd.DataFrame


def _is_non_model_column(column: str) -> bool:
    return column.endswith(_NON_MODEL_SUFFIXES)


def _family_matches(column: str, family: str) -> bool:
    if family == "objective_opportunity" and column in _OBJECTIVE_EXACT:
        return True
    return column.startswith(_FAMILY_PREFIXES[family])


def family_feature_columns(frame: pd.DataFrame, family: str) -> list[str]:
    return [
        column
        for column in frame.columns
        if _family_matches(column, family) and not _is_non_model_column(column)
    ]


def base_feature_columns(features: Iterable[str]) -> list[str]:
    output: list[str] = []
    for column in dict.fromkeys(features):
        if _is_non_model_column(column):
            continue
        if any(_family_matches(column, family) for family in _FAMILY_PREFIXES):
            continue
        output.append(column)
    return output


def build_incremental_feature_sets(
    base_features: Iterable[str], frame: pd.DataFrame
) -> dict[str, list[str]]:
    base = base_feature_columns(base_features)
    official = family_feature_columns(frame, "official_availability")
    objective = family_feature_columns(frame, "objective_opportunity")
    news = family_feature_columns(frame, "structured_news")
    public = family_feature_columns(frame, "public_player_context")

    variants: dict[str, list[str]] = {}
    variants["numerical_baseline"] = base
    variants["official_availability"] = list(dict.fromkeys([*base, *official]))
    variants["objective_reference"] = list(
        dict.fromkeys([*variants["official_availability"], *objective])
    )
    variants["structured_news"] = list(dict.fromkeys([*variants["objective_reference"], *news]))
    variants["public_player_context"] = list(
        dict.fromkeys([*variants["structured_news"], *public])
    )
    variants["official_availability_shuffled_control"] = variants["official_availability"]
    variants["objective_opportunity_shuffled_control"] = variants["objective_reference"]
    variants["structured_news_shuffled_control"] = variants["structured_news"]
    variants["public_player_context_shuffled_control"] = variants["public_player_context"]
    variants["official_availability_shifted_time_leakage_control"] = variants[
        "official_availability"
    ]
    variants["objective_opportunity_shifted_time_leakage_control"] = variants[
        "objective_reference"
    ]
    variants["structured_news_shifted_time_leakage_control"] = variants["structured_news"]
    variants["public_player_context_shifted_time_leakage_control"] = variants[
        "public_player_context"
    ]
    return variants


def _shuffle_family(frame: pd.DataFrame, family: str, *, seed: int) -> pd.DataFrame:
    output = frame.copy()
    columns = family_feature_columns(output, family)
    if not columns:
        return output
    strata = [column for column in ("season", "week", "position") if column in output]
    rng = np.random.default_rng(seed)
    if not strata:
        permutation = rng.permutation(len(output))
        output[columns] = output.iloc[permutation][columns].to_numpy()
        return output
    for _, indexes in output.groupby(strata, dropna=False, sort=False).groups.items():
        index = np.asarray(list(indexes))
        if len(index) < 2:
            continue
        permutation = rng.permutation(index)
        output.loc[index, columns] = output.loc[permutation, columns].to_numpy()
    return output


def _shift_family_forward_in_time(frame: pd.DataFrame, family: str) -> pd.DataFrame:
    """Leakage sensitivity control: move the next same-season player observation backward."""
    output = frame.reset_index(drop=True).copy()
    columns = family_feature_columns(output, family)
    if not columns:
        return output
    required = {"player_id", "season", "week"}
    missing = required - set(output.columns)
    if missing:
        raise ValueError(f"Shifted-time control missing columns: {sorted(missing)}")
    output["_row_order"] = np.arange(len(output))
    ordered = output.sort_values(["player_id", "season", "week", "_row_order"]).copy()
    ordered[columns] = ordered.groupby(["player_id", "season"], sort=False)[columns].shift(-1)
    return ordered.sort_values("_row_order").drop(columns="_row_order").reset_index(drop=True)


def _variant_frame(frame: pd.DataFrame, variant: str, *, seed: int) -> pd.DataFrame:
    for family in _FAMILY_PREFIXES:
        if variant == f"{family}_shuffled_control":
            return _shuffle_family(frame, family, seed=seed)
        if variant == f"{family}_shifted_time_leakage_control":
            return _shift_family_forward_in_time(frame, family)
    return frame


def run_incremental_intelligence_benchmark(
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
    """Run the frozen staircase and one-family-at-a-time negative controls."""
    variants = build_incremental_feature_sets(base_features, frame)
    runs: dict[str, AblationRun] = {}
    for name, features in variants.items():
        working = _variant_frame(frame, name, seed=seed)
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
            name=name,
            feature_count=len(features),
            result=result,
            artifact_paths=paths,
        )
    return runs


def _engine_predictions(run: AblationRun, target: str) -> pd.DataFrame:
    frame = run.result.predictions.loc[run.result.predictions["method"].eq("quantile_engine")].copy()
    required = {
        "season",
        "week",
        "player_id",
        "position",
        "actual",
        f"{target}_q10",
        f"{target}_q50",
        f"{target}_q90",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Ablation {run.name!r} missing prediction columns: {sorted(missing)}")
    keys = ["season", "week", "player_id"]
    if frame.duplicated(keys).any():
        raise ValueError(f"Ablation {run.name!r} has duplicate player-week predictions")
    return frame


def _row_pinball(frame: pd.DataFrame, target: str, prefix: str) -> np.ndarray:
    actual = pd.to_numeric(frame["actual"], errors="coerce").to_numpy(float)
    losses: list[np.ndarray] = []
    for quantile, label in ((0.1, "q10"), (0.5, "q50"), (0.9, "q90")):
        prediction = pd.to_numeric(
            frame[f"{prefix}{target}_{label}"], errors="coerce"
        ).to_numpy(float)
        error = actual - prediction
        losses.append(np.maximum(quantile * error, (quantile - 1.0) * error))
    return np.mean(np.vstack(losses), axis=0)


def _paired_predictions(reference: AblationRun, candidate: AblationRun, target: str) -> pd.DataFrame:
    reference_frame = _engine_predictions(reference, target)
    candidate_frame = _engine_predictions(candidate, target)
    keys = ["season", "week", "player_id"]
    keep = [*keys, "position", "actual", f"{target}_q10", f"{target}_q50", f"{target}_q90"]
    paired = reference_frame[keep].merge(
        candidate_frame[keep],
        on=keys,
        how="inner",
        suffixes=("_reference", "_candidate"),
        validate="one_to_one",
    )
    if paired.empty:
        raise ValueError(f"No paired player-weeks for {reference.name!r} vs {candidate.name!r}")
    actual_reference = pd.to_numeric(paired["actual_reference"], errors="coerce")
    actual_candidate = pd.to_numeric(paired["actual_candidate"], errors="coerce")
    mismatch = ~np.isclose(actual_reference, actual_candidate, equal_nan=False)
    if bool(mismatch.any()):
        raise ValueError("Paired ablation artifacts disagree on realized outcomes")
    position_mismatch = (
        paired["position_reference"].astype(str) != paired["position_candidate"].astype(str)
    )
    if bool(position_mismatch.any()):
        raise ValueError("Paired ablation artifacts disagree on player position")
    paired["actual"] = actual_reference
    paired["position"] = paired["position_reference"].astype(str)
    for side in ("reference", "candidate"):
        for label in ("q10", "q50", "q90"):
            paired[f"{side}_{target}_{label}"] = paired[f"{target}_{label}_{side}"]
    paired["reference_loss"] = _row_pinball(paired, target, "reference_")
    paired["candidate_loss"] = _row_pinball(paired, target, "candidate_")
    paired["effect"] = paired["reference_loss"] - paired["candidate_loss"]
    finite = np.isfinite(
        paired[["actual", "reference_loss", "candidate_loss", "effect"]]
    ).all(axis=1)
    return paired.loc[finite].reset_index(drop=True)


def _paired_bootstrap(
    paired: pd.DataFrame,
    *,
    effect_column: str = "effect",
    bootstrap_samples: int,
    seed: int,
) -> BootstrapEvidence:
    data = paired.dropna(subset=[effect_column, "season", "week"]).copy()
    data[effect_column] = pd.to_numeric(data[effect_column], errors="coerce")
    data = data.loc[np.isfinite(data[effect_column])]
    block_stats = data.groupby(["season", "week"], sort=False)[effect_column].agg(["sum", "count"])
    if len(block_stats) < 2:
        raise ValueError("Paired intelligence bootstrap requires at least two season-week blocks")
    block_sums = block_stats["sum"].to_numpy(float)
    block_counts = block_stats["count"].to_numpy(float)
    effect = float(block_sums.sum() / np.maximum(block_counts.sum(), 1.0))
    sample_count = max(200, int(bootstrap_samples))
    rng = np.random.default_rng(seed)
    indexes = rng.integers(0, len(block_stats), size=(sample_count, len(block_stats)))
    samples = block_sums[indexes].sum(axis=1) / np.maximum(
        block_counts[indexes].sum(axis=1), 1.0
    )
    low, high = np.quantile(samples, [0.025, 0.975])
    unfavorable = int(np.sum(samples <= 0.0))
    return BootstrapEvidence(
        effect=effect,
        ci_low=float(low),
        ci_high=float(high),
        probability_improves=float(np.mean(samples > 0.0)),
        p_value=float((unfavorable + 1) / (sample_count + 1)),
        blocks=int(len(block_stats)),
        bootstrap_samples=sample_count,
    )


def _truthy_rate(series: pd.Series) -> float:
    if pd.api.types.is_bool_dtype(series.dtype):
        return float(series.fillna(False).astype(bool).mean())
    numeric = pd.to_numeric(series, errors="coerce")
    text = series.astype("string").str.strip().str.lower()
    mapped = text.map(
        {"true": 1.0, "yes": 1.0, "y": 1.0, "false": 0.0, "no": 0.0, "n": 0.0}
    )
    values = numeric.where(numeric.notna(), mapped).fillna(0.0)
    return float((values > 0.0).mean())


def _first_rate(frame: pd.DataFrame, columns: tuple[str, ...]) -> float | None:
    for column in columns:
        if column in frame:
            return _truthy_rate(frame[column])
    return None


def _conflict_rate(frame: pd.DataFrame, family: str) -> float | None:
    for column in _CONFLICT_COLUMNS[family]:
        if column in frame:
            values = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
            return float((values > 0.0).mean())
    return None


def _frame_for_pairs(frame: pd.DataFrame, paired: pd.DataFrame) -> pd.DataFrame:
    keys = ["season", "week", "player_id"]
    source = frame.copy()
    if "is_projection_row" in source:
        source = source.loc[~source["is_projection_row"].astype(bool)].copy()
    source["player_id"] = source["player_id"].astype(str)
    if source.duplicated(keys).any():
        raise ValueError("Feature table has duplicate season/week/player_id rows")
    key_frame = paired[keys].copy()
    key_frame["player_id"] = key_frame["player_id"].astype(str)
    return key_frame.merge(source, on=keys, how="left", validate="one_to_one")


def _coverage_metrics(paired: pd.DataFrame, target: str, side: str) -> tuple[float, float]:
    actual = pd.to_numeric(paired["actual"], errors="coerce").to_numpy(float)
    low = pd.to_numeric(paired[f"{side}_{target}_q10"], errors="coerce").to_numpy(float)
    high = pd.to_numeric(paired[f"{side}_{target}_q90"], errors="coerce").to_numpy(float)
    covered = (actual >= low) & (actual <= high)
    coverage = float(np.mean(covered))
    return coverage, abs(coverage - 0.80)


def _max_position_coverage_regression(
    paired: pd.DataFrame,
    target: str,
    *,
    min_position_rows: int,
) -> tuple[float | None, int]:
    regressions: list[float] = []
    supported = 0
    for _, subset in paired.groupby("position", dropna=False):
        if len(subset) < min_position_rows:
            continue
        supported += 1
        _, reference_gap = _coverage_metrics(subset, target, "reference")
        _, candidate_gap = _coverage_metrics(subset, target, "candidate")
        regressions.append(candidate_gap - reference_gap)
    return (max(regressions) if regressions else None), supported


def _q50_mae(paired: pd.DataFrame, target: str, side: str) -> float:
    actual = pd.to_numeric(paired["actual"], errors="coerce").to_numpy(float)
    median = pd.to_numeric(paired[f"{side}_{target}_q50"], errors="coerce").to_numpy(float)
    return float(np.mean(np.abs(actual - median)))


def evaluate_incremental_intelligence_evidence(
    frame: pd.DataFrame,
    runs: dict[str, AblationRun],
    target: str,
    *,
    bootstrap_samples: int = 2000,
    seed: int = 42,
    minimum_effect: float = 0.0,
    maximum_fdr_q: float = 0.10,
    minimum_consistency: float = 0.55,
    minimum_source_coverage: float = 0.80,
    maximum_overall_coverage_gap_regression: float = 0.02,
    maximum_position_coverage_gap_regression: float = 0.05,
    minimum_position_rows: int = 50,
    minimum_paired_rows: int = 250,
    minimum_seasons: int = 2,
    minimum_blocks: int = 8,
) -> pd.DataFrame:
    """Evaluate incremental family lift without granting production authority."""
    candidate_rows: list[dict[str, object]] = []
    raw_p_values: dict[str, float] = {}

    for candidate_index, (family, reference_name, candidate_name) in enumerate(
        _CANDIDATE_SEQUENCE
    ):
        reference = runs[reference_name]
        candidate = runs[candidate_name]
        paired = _paired_predictions(reference, candidate, target)
        primary = _paired_bootstrap(
            paired,
            bootstrap_samples=bootstrap_samples,
            seed=seed + 100 * candidate_index,
        )
        shuffled_name = f"{family}_shuffled_control"
        shifted_name = f"{family}_shifted_time_leakage_control"
        identity_pair = _paired_predictions(runs[shuffled_name], candidate, target)
        identity = _paired_bootstrap(
            identity_pair,
            bootstrap_samples=bootstrap_samples,
            seed=seed + 100 * candidate_index + 1,
        )
        leakage_pair = _paired_predictions(candidate, runs[shifted_name], target)
        leakage = _paired_bootstrap(
            leakage_pair,
            bootstrap_samples=bootstrap_samples,
            seed=seed + 100 * candidate_index + 2,
        )

        paired_rows = _frame_for_pairs(frame, paired)
        source_coverage = _first_rate(paired_rows, _SOURCE_COVERAGE_COLUMNS[family])
        claim_prevalence = _first_rate(paired_rows, _PREVALENCE_COLUMNS[family])
        contradiction_rate = _conflict_rate(paired_rows, family)
        reference_coverage, reference_gap = _coverage_metrics(paired, target, "reference")
        candidate_coverage, candidate_gap = _coverage_metrics(paired, target, "candidate")
        max_position_regression, supported_positions = _max_position_coverage_regression(
            paired, target, min_position_rows=min_position_rows
        )
        seasons = int(paired["season"].nunique())
        blocks = int(paired[["season", "week"]].drop_duplicates().shape[0])
        season_consistency = consistency_rate(
            paired, effect_column="effect", group_columns=("season",)
        )
        position_consistency = consistency_rate(
            paired, effect_column="effect", group_columns=("position",)
        )
        week_consistency = consistency_rate(
            paired, effect_column="effect", group_columns=("season", "week")
        )

        experiment_id = f"structured-intelligence:{target}:{family}"
        raw_p_values[experiment_id] = primary.p_value
        candidate_rows.append(
            {
                "experiment_id": experiment_id,
                "family": family,
                "target": target,
                "reference": reference_name,
                "candidate": candidate_name,
                "authority": "research_evidence_only",
                "automatic_promotion": False,
                "production_projection_changed": False,
                "paired_rows": int(len(paired)),
                "paired_seasons": seasons,
                "paired_blocks": blocks,
                "reference_mean_pinball": float(paired["reference_loss"].mean()),
                "candidate_mean_pinball": float(paired["candidate_loss"].mean()),
                "effect": primary.effect,
                "ci_low": primary.ci_low,
                "ci_high": primary.ci_high,
                "probability_improves": primary.probability_improves,
                "p_value": primary.p_value,
                "bootstrap_samples": primary.bootstrap_samples,
                "reference_q50_mae": _q50_mae(paired, target, "reference"),
                "candidate_q50_mae": _q50_mae(paired, target, "candidate"),
                "reference_80_coverage": reference_coverage,
                "candidate_80_coverage": candidate_coverage,
                "coverage_gap_regression": candidate_gap - reference_gap,
                "max_supported_position_coverage_gap_regression": max_position_regression,
                "supported_position_slices": supported_positions,
                "season_consistency": season_consistency,
                "position_consistency": position_consistency,
                "week_consistency": week_consistency,
                "identity_control_effect": identity.effect,
                "identity_control_ci_low": identity.ci_low,
                "identity_control_ci_high": identity.ci_high,
                "identity_control_passed": bool(
                    identity.effect > 0.0 and identity.ci_low > 0.0
                ),
                "shifted_time_leakage_advantage": leakage.effect,
                "shifted_time_leakage_ci_low": leakage.ci_low,
                "shifted_time_leakage_ci_high": leakage.ci_high,
                "source_coverage": source_coverage,
                "claim_prevalence": claim_prevalence,
                "contradiction_rate": contradiction_rate,
                "evidence_tier": (
                    "multi_season_isolated" if seasons >= 2 else "single_historical_slice"
                ),
            }
        )

    q_values = benjamini_hochberg(raw_p_values)
    for row in candidate_rows:
        q_value = q_values.get(str(row["experiment_id"]))
        row["fdr_q_value"] = q_value
        blockers: list[str] = []
        if int(row["paired_rows"]) < minimum_paired_rows:
            blockers.append("paired_rows_below_minimum")
        if int(row["paired_seasons"]) < minimum_seasons:
            blockers.append("multi_season_evidence_missing")
        if int(row["paired_blocks"]) < minimum_blocks:
            blockers.append("paired_blocks_below_minimum")
        if not np.isfinite(float(row["effect"])) or float(row["effect"]) <= minimum_effect:
            blockers.append("incremental_effect_not_positive")
        if not np.isfinite(float(row["ci_low"])) or float(row["ci_low"]) <= 0.0:
            blockers.append("incremental_effect_ci_not_positive")
        if q_value is None or not np.isfinite(q_value) or q_value > maximum_fdr_q:
            blockers.append("fdr_q_above_threshold_or_missing")
        for label in ("season", "position", "week"):
            value = float(row[f"{label}_consistency"])
            if not np.isfinite(value):
                blockers.append(f"missing_{label}_consistency")
            elif value < minimum_consistency:
                blockers.append(f"inconsistent_{label}_effect")
        if not bool(row["identity_control_passed"]):
            blockers.append("identity_negative_control_failed")
        source_coverage = row["source_coverage"]
        if source_coverage is None or not np.isfinite(float(source_coverage)):
            blockers.append("source_coverage_not_measured")
        elif float(source_coverage) < minimum_source_coverage:
            blockers.append("source_coverage_below_threshold")
        if float(row["coverage_gap_regression"]) > maximum_overall_coverage_gap_regression:
            blockers.append("overall_calibration_regression")
        position_regression = row["max_supported_position_coverage_gap_regression"]
        if position_regression is None:
            blockers.append("position_calibration_not_measured")
        elif float(position_regression) > maximum_position_coverage_gap_regression:
            blockers.append("position_calibration_regression")
        row["activation_review_blockers"] = blockers
        row["eligible_for_activation_review"] = not blockers
    return pd.DataFrame(candidate_rows)


def run_structured_intelligence_evidence_experiment(
    frame: pd.DataFrame,
    base_features: Iterable[str],
    target: str,
    config: ModelConfig,
    *,
    output_dir: str | Path | None = None,
    min_train_weeks: int = 24,
    retrain_every_weeks: int = 4,
    rolling_window: int = 5,
    bootstrap_samples: int = 2000,
    seed: int = 42,
    minimum_effect: float = 0.0,
    maximum_fdr_q: float = 0.10,
    minimum_consistency: float = 0.55,
    minimum_source_coverage: float = 0.80,
    maximum_overall_coverage_gap_regression: float = 0.02,
    maximum_position_coverage_gap_regression: float = 0.05,
    minimum_position_rows: int = 50,
    minimum_paired_rows: int = 250,
    minimum_seasons: int = 2,
    minimum_blocks: int = 8,
) -> IntelligenceEvidenceRun:
    runs = run_incremental_intelligence_benchmark(
        frame,
        base_features,
        target,
        config,
        output_dir=output_dir,
        min_train_weeks=min_train_weeks,
        retrain_every_weeks=retrain_every_weeks,
        rolling_window=rolling_window,
        seed=seed,
    )
    evidence = evaluate_incremental_intelligence_evidence(
        frame,
        runs,
        target,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
        minimum_effect=minimum_effect,
        maximum_fdr_q=maximum_fdr_q,
        minimum_consistency=minimum_consistency,
        minimum_source_coverage=minimum_source_coverage,
        maximum_overall_coverage_gap_regression=maximum_overall_coverage_gap_regression,
        maximum_position_coverage_gap_regression=maximum_position_coverage_gap_regression,
        minimum_position_rows=minimum_position_rows,
        minimum_paired_rows=minimum_paired_rows,
        minimum_seasons=minimum_seasons,
        minimum_blocks=minimum_blocks,
    )
    return IntelligenceEvidenceRun(runs=runs, evidence=evidence)
