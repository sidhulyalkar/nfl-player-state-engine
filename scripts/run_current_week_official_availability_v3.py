from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import run_rebaselined_historical_intelligence_experiment_v2 as source_runner

from player_state_engine.config import load_config
from player_state_engine.data.io import read_table, write_table
from player_state_engine.evaluation.ablations import AblationRun
from player_state_engine.evaluation.benchmark import run_multiseason_benchmark
from player_state_engine.evaluation.historical_intelligence_corpus import (
    _game_status,
    _latest_injury_rows,
    _panel_with_cutoffs,
    _practice_status,
)
from player_state_engine.evaluation.intelligence_evidence import (
    _coverage_metrics,
    _max_position_coverage_regression,
    _paired_bootstrap,
    _paired_predictions,
    _q50_mae,
    base_feature_columns,
)
from player_state_engine.evaluation.reporting import persist_benchmark
from player_state_engine.features.weekly import build_weekly_features, feature_columns_for_target
from player_state_engine.intelligence.availability import GAME_SCORE, PRACTICE_SCORE
from player_state_engine.state_graph.experiments import benjamini_hochberg, consistency_rate

_SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}
_UNVERIFIED_FINAL_CONTEXT = {"spread_line", "total_line", "roof", "temp", "wind"}
_FORMULATIONS: dict[str, tuple[str, ...]] = {
    "practice_current_week": (
        "cw_practice_score",
        "cw_practice_is_limited",
        "cw_practice_is_dnp",
        "cw_practice_found",
    ),
    "game_designation_current_week": (
        "cw_game_score",
        "cw_game_is_questionable",
        "cw_game_is_doubtful",
        "cw_game_is_out",
        "cw_game_found",
    ),
    "combined_current_week": (
        "cw_practice_score",
        "cw_practice_is_limited",
        "cw_practice_is_dnp",
        "cw_practice_found",
        "cw_game_score",
        "cw_game_is_questionable",
        "cw_game_is_doubtful",
        "cw_game_is_out",
        "cw_game_found",
        "cw_any_report_found",
    ),
}


def _shuffle_columns(frame: pd.DataFrame, columns: tuple[str, ...], seed: int) -> pd.DataFrame:
    output = frame.copy()
    rng = np.random.default_rng(seed)
    strata = [column for column in ("season", "week", "position") if column in output]
    for _, indexes in output.groupby(strata, dropna=False, sort=False).groups.items():
        index = np.asarray(list(indexes))
        if len(index) < 2:
            continue
        permutation = rng.permutation(index)
        output.loc[index, list(columns)] = output.loc[permutation, list(columns)].to_numpy()
    return output


def _shift_forward(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    output = frame.reset_index(drop=True).copy()
    output["_row_order"] = np.arange(len(output))
    ordered = output.sort_values(["player_id", "season", "week", "_row_order"]).copy()
    ordered[list(columns)] = ordered.groupby(["player_id", "season"], sort=False)[
        list(columns)
    ].shift(-1)
    return ordered.sort_values("_row_order").drop(columns="_row_order").reset_index(drop=True)


def _run(
    frame: pd.DataFrame,
    features: list[str],
    target: str,
    config,
    name: str,
    output_dir: Path,
) -> AblationRun:
    result = run_multiseason_benchmark(
        frame,
        features,
        target,
        config=config,
        min_train_weeks=24,
        retrain_every_weeks=4,
        rolling_window=5,
    )
    paths = persist_benchmark(result, target, output_dir / name)
    return AblationRun(name=name, feature_count=len(features), result=result, artifact_paths=paths)


def _paired_source_rows(frame: pd.DataFrame, paired: pd.DataFrame) -> pd.DataFrame:
    keys = ["season", "week", "player_id"]
    audit = frame.drop_duplicates(keys).merge(
        paired[keys].drop_duplicates(),
        on=keys,
        how="inner",
        validate="one_to_one",
    )
    if len(audit) != len(paired):
        raise ValueError(
            f"Current-week source audit rows disagree with paired predictions: {len(audit)} != {len(paired)}"
        )
    return audit


def _build_current_week_frame(
    features: pd.DataFrame,
    schedules: pd.DataFrame,
    injuries: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    panel_keys = ["season", "week", "game_id", "player_id", "recent_team"]
    panel_cutoffs = _panel_with_cutoffs(features[panel_keys], schedules, cutoff_hours_before=1.5)
    selected, coverage = _latest_injury_rows(panel_cutoffs, injuries)

    selected_columns = [
        "season",
        "week",
        "game_id",
        "player_id",
        "recent_team",
        "practice_status",
        "report_status",
        "date_modified",
    ]
    current = panel_cutoffs.merge(
        selected[selected_columns],
        on=panel_keys,
        how="left",
        validate="one_to_one",
    )
    current = current.merge(
        coverage[
            [
                "season",
                "week",
                "player_id",
                "official_injury_report_source_covered",
                "injury_source_first_observed_at",
            ]
        ],
        on=["season", "week", "player_id"],
        how="left",
        validate="one_to_one",
    )

    practice = current["practice_status"].map(_practice_status)
    game = current["report_status"].map(_game_status)
    practice_found = practice.ne("unknown") & current["date_modified"].notna()
    game_found = game.ne("unknown") & current["date_modified"].notna()

    current["cw_practice_score"] = practice.map(PRACTICE_SCORE).where(practice_found)
    current["cw_practice_is_limited"] = practice.eq("limited").where(practice_found).astype("Float64")
    current["cw_practice_is_dnp"] = (
        practice.eq("did_not_participate").where(practice_found).astype("Float64")
    )
    current["cw_practice_found"] = practice_found.astype(int)

    current["cw_game_score"] = game.map(GAME_SCORE).where(game_found)
    current["cw_game_is_questionable"] = (
        game.eq("questionable").where(game_found).astype("Float64")
    )
    current["cw_game_is_doubtful"] = game.eq("doubtful").where(game_found).astype("Float64")
    current["cw_game_is_out"] = (
        game.isin({"out", "ir", "pup", "suspended"}).where(game_found).astype("Float64")
    )
    current["cw_game_found"] = game_found.astype(int)
    current["cw_any_report_found"] = (practice_found | game_found).astype(int)
    current["official_availability_source_covered"] = current[
        "official_injury_report_source_covered"
    ].fillna(False).astype(bool)

    merge_columns = [
        *panel_keys,
        "prediction_cutoff",
        "date_modified",
        "injury_source_first_observed_at",
        "official_availability_source_covered",
        *sorted({column for columns in _FORMULATIONS.values() for column in columns}),
    ]
    output = features.merge(
        current[merge_columns],
        on=panel_keys,
        how="left",
        validate="one_to_one",
    )
    if output["prediction_cutoff"].isna().any():
        raise ValueError("Current-week exploration has rows without a proven prediction cutoff")

    preflight = {
        "rows": int(len(output)),
        "source_coverage": float(output["official_availability_source_covered"].mean()),
        "practice_prevalence": float(output["cw_practice_found"].mean()),
        "game_designation_prevalence": float(output["cw_game_found"].mean()),
        "any_report_prevalence": float(output["cw_any_report_found"].mean()),
        "prediction_cutoff_missing_rows": int(output["prediction_cutoff"].isna().sum()),
        "latest_evidence_after_cutoff_rows": int(
            (
                output["date_modified"].notna()
                & output["date_modified"].gt(output["prediction_cutoff"])
            ).sum()
        ),
    }
    if preflight["latest_evidence_after_cutoff_rows"] != 0:
        raise ValueError("Current-week availability contains evidence after the prediction cutoff")
    return output, preflight


def _evaluate_formulation(
    frame: pd.DataFrame,
    baseline: AblationRun,
    base_features: list[str],
    formulation: str,
    columns: tuple[str, ...],
    target: str,
    config,
    output_dir: Path,
    bootstrap_samples: int,
    seed: int,
) -> dict[str, object]:
    candidate_features = [*base_features, *columns]
    candidate = _run(
        frame,
        candidate_features,
        target,
        config,
        formulation,
        output_dir,
    )
    shuffled = _run(
        _shuffle_columns(frame, columns, seed=seed),
        candidate_features,
        target,
        config,
        f"{formulation}_shuffled_control",
        output_dir,
    )
    shifted = _run(
        _shift_forward(frame, columns),
        candidate_features,
        target,
        config,
        f"{formulation}_shifted_time_control",
        output_dir,
    )

    paired = _paired_predictions(baseline, candidate, target)
    primary = _paired_bootstrap(paired, bootstrap_samples=bootstrap_samples, seed=seed)
    identity_pair = _paired_predictions(shuffled, candidate, target)
    identity = _paired_bootstrap(
        identity_pair,
        bootstrap_samples=bootstrap_samples,
        seed=seed + 1,
    )
    leakage_pair = _paired_predictions(candidate, shifted, target)
    leakage = _paired_bootstrap(
        leakage_pair,
        bootstrap_samples=bootstrap_samples,
        seed=seed + 2,
    )

    audited = _paired_source_rows(frame, paired)
    reference_coverage, reference_gap = _coverage_metrics(paired, target, "reference")
    candidate_coverage, candidate_gap = _coverage_metrics(paired, target, "candidate")
    max_position_regression, supported_positions = _max_position_coverage_regression(
        paired,
        target,
        min_position_rows=50,
    )
    result: dict[str, object] = {
        "formulation": formulation,
        "authority": "posthoc_exploratory_research_only",
        "automatic_promotion": False,
        "eligible_for_activation_review": False,
        "activation_review_blockers": ["posthoc_formulation_requires_independent_confirmation"],
        "features": list(columns),
        "paired_rows": int(len(paired)),
        "paired_seasons": int(paired["season"].nunique()),
        "paired_blocks": int(paired[["season", "week"]].drop_duplicates().shape[0]),
        "reference_mean_pinball": float(paired["reference_loss"].mean()),
        "candidate_mean_pinball": float(paired["candidate_loss"].mean()),
        "effect": primary.effect,
        "ci_low": primary.ci_low,
        "ci_high": primary.ci_high,
        "probability_improves": primary.probability_improves,
        "p_value": primary.p_value,
        "season_consistency": consistency_rate(
            paired, effect_column="effect", group_columns=("season",)
        ),
        "position_consistency": consistency_rate(
            paired, effect_column="effect", group_columns=("position",)
        ),
        "week_consistency": consistency_rate(
            paired, effect_column="effect", group_columns=("season", "week")
        ),
        "reference_q50_mae": _q50_mae(paired, target, "reference"),
        "candidate_q50_mae": _q50_mae(paired, target, "candidate"),
        "reference_80_coverage": reference_coverage,
        "candidate_80_coverage": candidate_coverage,
        "coverage_gap_regression": candidate_gap - reference_gap,
        "max_supported_position_coverage_gap_regression": max_position_regression,
        "supported_position_slices": supported_positions,
        "identity_control_effect": identity.effect,
        "identity_control_ci_low": identity.ci_low,
        "identity_control_ci_high": identity.ci_high,
        "identity_control_passed": bool(identity.effect > 0.0 and identity.ci_low > 0.0),
        "shifted_time_leakage_advantage": leakage.effect,
        "shifted_time_leakage_ci_low": leakage.ci_low,
        "shifted_time_leakage_ci_high": leakage.ci_high,
        "source_coverage": float(audited["official_availability_source_covered"].mean()),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Post-hoc exploratory follow-up to the failed v2 structured-availability experiment. "
            "Tests current-week reset semantics and decomposes practice vs game designation. "
            "Results are never eligible for activation without independent confirmation."
        )
    )
    parser.add_argument(
        "--numerical-root",
        type=Path,
        default=Path("data/raw/historical_numerical_baseline_v2"),
    )
    parser.add_argument(
        "--injury-root",
        type=Path,
        default=Path("data/raw/historical_injury_archive_v2"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/intelligence_ablations/current_week_official_v3"),
    )
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=4203)
    args = parser.parse_args()

    config = load_config(Path("configs/base.yaml"))
    manifest, numerical_paths = source_runner._verify_numerical_manifest(
        args.numerical_root / "NUMERICAL_BASELINE_MANIFEST.json"
    )
    expected_identity = "a036c410e0bb1ec670e3fa0f7d6e14e1433322b6eeabdaa81c25c8daee43a29c"
    if str(manifest.get("identity_sha256")) != expected_identity:
        raise ValueError("v3 exploration requires the exact registered v2 numerical baseline")

    seasons = (2020, 2021, 2022, 2023, 2024)
    raw_stats = pd.concat(
        [read_table(numerical_paths[f"player_stats_{season}"]) for season in seasons],
        ignore_index=True,
        sort=False,
    )
    schedules = read_table(numerical_paths["schedules"])
    features = build_weekly_features(raw_stats, schedules=schedules, config=config.features)
    features = features.loc[
        features["season"].astype(int).isin(seasons)
        & features["position"].astype(str).str.upper().isin(_SKILL_POSITIONS)
        & ~features["is_projection_row"].fillna(False).astype(bool)
        & features["season_type"].astype(str).str.upper().eq("REG")
    ].copy()
    if features.empty:
        raise ValueError("v3 current-week exploration produced no REG skill-position rows")

    injuries, _, injury_verification = source_runner._injury_archive(args.injury_root)
    if not injury_verification.verified:
        raise ValueError("v3 current-week exploration requires a verified injury archive")

    frame, preflight = _build_current_week_frame(features, schedules, injuries)
    base_features = base_feature_columns(feature_columns_for_target(frame, "fantasy_points_ppr"))
    base_features = [column for column in base_features if column not in _UNVERIFIED_FINAL_CONTEXT]
    if not base_features:
        raise ValueError("v3 current-week exploration produced no numerical baseline features")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "source_coverage_preflight.json").write_text(
        json.dumps(preflight, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_table(frame, args.output_dir / "current_week_feature_frame.parquet")

    baseline = _run(
        frame,
        base_features,
        "fantasy_points_ppr",
        config.model,
        "numerical_baseline",
        args.output_dir / "variants",
    )

    rows: list[dict[str, object]] = []
    for index, (name, columns) in enumerate(_FORMULATIONS.items()):
        rows.append(
            _evaluate_formulation(
                frame,
                baseline,
                base_features,
                name,
                columns,
                "fantasy_points_ppr",
                config.model,
                args.output_dir / "variants",
                args.bootstrap_samples,
                args.seed + index * 100,
            )
        )

    q_values = benjamini_hochberg({str(row["formulation"]): float(row["p_value"]) for row in rows})
    for row in rows:
        row["exploratory_joint_fdr_q"] = q_values[str(row["formulation"])]
        screen_blockers: list[str] = []
        if float(row["effect"]) <= 0.0 or float(row["ci_low"]) <= 0.0:
            screen_blockers.append("incremental_effect_not_credibly_positive")
        if float(row["exploratory_joint_fdr_q"]) > 0.10:
            screen_blockers.append("joint_exploratory_fdr_q_above_0_10")
        for label in ("season", "position", "week"):
            if float(row[f"{label}_consistency"]) < 0.55:
                screen_blockers.append(f"inconsistent_{label}_effect")
        if not bool(row["identity_control_passed"]):
            screen_blockers.append("identity_negative_control_failed")
        if float(row["coverage_gap_regression"]) > 0.02:
            screen_blockers.append("overall_calibration_regression")
        position_regression = row["max_supported_position_coverage_gap_regression"]
        if position_regression is None or float(position_regression) > 0.05:
            screen_blockers.append("position_calibration_regression")
        row["exploratory_screen_blockers"] = screen_blockers
        row["exploratory_screen_passed"] = not screen_blockers
        row["eligible_for_activation_review"] = False

    result_frame = pd.DataFrame(rows)
    result_frame.to_csv(args.output_dir / "formulation_results.csv", index=False)
    manifest_payload = {
        "schema_version": 1,
        "experiment_id": "current-week-official-availability-v3-posthoc-exploration",
        "authority": "posthoc_exploratory_research_only",
        "automatic_promotion": False,
        "eligible_for_activation_review": False,
        "hypothesis_origin": (
            "Formulation was designed after observing the v2 negative result and stale-claim "
            "diagnostics. Historical results may screen candidates but cannot confirm one."
        ),
        "source_identity": {
            "numerical_baseline_identity_sha256": manifest["identity_sha256"],
            "injury_archive_identity_sha256": injury_verification.archive_identity_sha256,
        },
        "evaluation": {
            "season_type": "REG",
            "seasons": list(seasons),
            "target": "fantasy_points_ppr",
            "prediction_cutoff_hours_before_kickoff": 1.5,
            "bootstrap_samples": int(args.bootstrap_samples),
            "unverified_final_context_removed": sorted(_UNVERIFIED_FINAL_CONTEXT),
        },
        "preflight": preflight,
        "formulations": rows,
        "next_authority_boundary": (
            "Any formulation that passes this exploratory screen still requires independent, "
            "untouched or prospective confirmation before manual activation review."
        ),
    }
    (args.output_dir / "run_manifest.json").write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest_payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
