from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

import pandas as pd

from player_state_engine.config import EngineConfig
from player_state_engine.data.io import read_table, write_table
from player_state_engine.data.synthetic import write_synthetic_dataset
from player_state_engine.evaluation.benchmark import run_multiseason_benchmark
from player_state_engine.evaluation.metrics import evaluate_quantiles
from player_state_engine.evaluation.reporting import persist_benchmark
from player_state_engine.features.intelligence import attach_point_in_time_intelligence
from player_state_engine.features.weekly import (
    build_prediction_slate,
    build_weekly_features,
    feature_columns,
    feature_columns_for_target,
)
from player_state_engine.models.hybrid import HybridQuantileModelBundle
from player_state_engine.simulation.game import simulate_slate


def build_features_workflow(
    stats_path: str | Path,
    schedules_path: str | Path,
    output_path: str | Path,
    config: EngineConfig,
) -> Path:
    stats = read_table(stats_path)
    schedules = read_table(schedules_path)
    featured = build_weekly_features(stats, schedules=schedules, config=config.features)
    return write_table(featured, output_path)


def train_workflow(
    features_path: str | Path,
    model_path: str | Path,
    config: EngineConfig,
    targets: Iterable[str] | None = None,
    holdout_weeks: int = 4,
    metrics_path: str | Path | None = None,
) -> tuple[Path, pd.DataFrame]:
    frame = read_table(features_path)
    actual_mask = (
        ~frame["is_projection_row"].astype(bool)
        if "is_projection_row" in frame
        else pd.Series(True, index=frame.index)
    )
    actual = frame.loc[actual_mask].copy()
    actual = actual.loc[actual["player_history_count"] >= config.features.min_player_history]
    actual["fold_week"] = actual["season"] * 25 + actual["week"]
    unique_weeks = sorted(actual["fold_week"].unique())
    if len(unique_weeks) <= holdout_weeks:
        raise ValueError("Not enough weeks to create a temporal holdout.")
    holdout_start = unique_weeks[-holdout_weeks]
    train = actual.loc[actual["fold_week"] < holdout_start]
    validation = actual.loc[actual["fold_week"] >= holdout_start]

    requested_targets = tuple(targets or config.model.targets)
    available_targets = tuple(target for target in requested_targets if target in actual.columns)
    features = feature_columns(actual, targets=available_targets)
    bundle = HybridQuantileModelBundle(config=config.model).fit(train, features, available_targets)
    predictions = bundle.predict(validation)

    rows: list[dict[str, object]] = []
    for target in bundle.targets:
        row: dict[str, object] = {"target": target, "validation_rows": len(validation)}
        row.update(
            evaluate_quantiles(validation[target], predictions, target, config.model.quantiles)
        )
        rows.append(row)
    metrics = pd.DataFrame(rows)

    path = bundle.save(model_path)
    if metrics_path:
        write_table(metrics, metrics_path)
        manifest = {
            "model_path": str(path),
            "features": bundle.features,
            "targets": bundle.targets,
            "training_summary": bundle.training_summary,
            "temporal_holdout_start": int(holdout_start),
        }
        manifest_path = Path(metrics_path).with_suffix(".manifest.json")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path, metrics


def make_slate_workflow(
    stats_path: str | Path,
    schedules_path: str | Path,
    output_path: str | Path,
    season: int,
    week: int,
    config: EngineConfig,
) -> Path:
    stats = read_table(stats_path)
    schedules = read_table(schedules_path)
    slate = build_prediction_slate(
        stats, schedules, season=season, week=week, config=config.features
    )
    return write_table(slate, output_path)


def predict_workflow(
    model_path: str | Path,
    slate_path: str | Path,
    output_path: str | Path,
) -> Path:
    bundle = HybridQuantileModelBundle.load(model_path)
    slate = read_table(slate_path)
    predictions = bundle.predict(slate)
    return write_table(predictions, output_path)


def simulate_workflow(
    predictions_path: str | Path,
    output_dir: str | Path,
    config: EngineConfig,
    target: str = "fantasy_points_ppr",
) -> dict[str, Path]:
    predictions = read_table(predictions_path)
    result = simulate_slate(
        predictions,
        target=target,
        draws=config.simulation.draws,
        same_team_correlation=config.simulation.same_team_correlation,
        opposing_team_correlation=config.simulation.opposing_team_correlation,
        seed=config.simulation.seed,
    )
    output_dir = Path(output_dir)
    return {
        "players": write_table(
            result.player_summary, output_dir / f"{target}_player_simulation.csv"
        ),
        "teams": write_table(result.team_summary, output_dir / f"{target}_team_simulation.csv"),
        "games": write_table(result.game_summary, output_dir / f"{target}_game_simulation.csv"),
    }


def benchmark_workflow(
    features_path: str | Path,
    output_dir: str | Path,
    target: str,
    config: EngineConfig,
    min_train_weeks: int | None = None,
    retrain_every_weeks: int | None = None,
    rolling_window: int | None = None,
) -> dict[str, Path]:
    frame = read_table(features_path)
    features = feature_columns_for_target(frame, target)
    result = run_multiseason_benchmark(
        frame,
        features,
        target=target,
        config=replace(config.model, targets=(target,)),
        min_train_weeks=min_train_weeks or config.benchmark.min_train_weeks,
        retrain_every_weeks=retrain_every_weeks or config.benchmark.retrain_every_weeks,
        rolling_window=rolling_window or config.benchmark.rolling_window,
    )
    return persist_benchmark(result, target, output_dir)


def attach_intelligence_workflow(
    features_path: str | Path,
    intelligence_path: str | Path,
    output_path: str | Path,
    config: EngineConfig,
) -> Path:
    football = read_table(features_path)
    intelligence = read_table(intelligence_path)
    joined = attach_point_in_time_intelligence(
        football,
        intelligence,
        safety_lag_hours=config.intelligence.safety_lag_hours,
    )
    return write_table(joined, output_path)


def smoke_test_workflow(work_dir: str | Path, config: EngineConfig) -> dict[str, Path]:
    work_dir = Path(work_dir)
    raw_dir = work_dir / "data" / "raw"
    processed_dir = work_dir / "data" / "processed"
    model_dir = work_dir / "artifacts" / "models"
    prediction_dir = work_dir / "artifacts" / "predictions"
    report_dir = work_dir / "artifacts" / "reports"

    write_synthetic_dataset(
        raw_dir, seasons=(2023, 2024), weeks_per_season=12, seed=config.random_seed
    )
    features_path = build_features_workflow(
        raw_dir / "player_stats.csv",
        raw_dir / "schedules.csv",
        processed_dir / "weekly_features.csv",
        config,
    )

    smoke_model = replace(
        config.model,
        targets=("fantasy_points_ppr", "targets", "carries", "passing_yards"),
        max_iter=min(config.model.max_iter, 45),
        min_samples_leaf=min(config.model.min_samples_leaf, 10),
    )
    smoke_config = replace(config, model=smoke_model)
    model_path, _ = train_workflow(
        features_path,
        model_dir / "quantile_bundle.joblib",
        smoke_config,
        holdout_weeks=3,
        metrics_path=report_dir / "holdout_metrics.csv",
    )

    # Forecast a synthetic future week by extending the deterministic schedule.
    from player_state_engine.data.synthetic import generate_synthetic_dataset

    extended = generate_synthetic_dataset(
        seasons=(2023, 2024), weeks_per_season=13, seed=config.random_seed
    )
    write_table(extended.schedules, raw_dir / "schedules_extended.csv")
    slate_path = make_slate_workflow(
        raw_dir / "player_stats.csv",
        raw_dir / "schedules_extended.csv",
        processed_dir / "slate_2024_w13.csv",
        season=2024,
        week=13,
        config=smoke_config,
    )
    predictions_path = predict_workflow(
        model_path,
        slate_path,
        prediction_dir / "predictions_2024_w13.csv",
    )
    simulation_paths = simulate_workflow(
        predictions_path,
        report_dir,
        replace(smoke_config, simulation=replace(smoke_config.simulation, draws=1_000)),
    )
    return {
        "features": Path(features_path),
        "model": Path(model_path),
        "slate": Path(slate_path),
        "predictions": Path(predictions_path),
        **simulation_paths,
    }


def calibrate_predictions_workflow(
    predictions_path: str | Path,
    target: str,
    output_dir: str | Path,
    config: EngineConfig,
) -> dict[str, Path]:
    from player_state_engine.evaluation.calibration import (
        interval_calibration_table,
        quantile_calibration_table,
    )
    from player_state_engine.evaluation.metrics import evaluate_quantiles
    from player_state_engine.models.conformal import apply_earlier_season_conformal

    predictions = read_table(predictions_path)
    calibrated, diagnostics = apply_earlier_season_conformal(
        predictions,
        target,
        config.model.quantiles,
        minimum_calibration_seasons=config.conformal.minimum_calibration_seasons,
        min_group_rows=config.conformal.min_group_rows,
        shrinkage_rows=config.conformal.shrinkage_rows,
    )
    raw = predictions.loc[predictions["method"] == "quantile_engine"].copy()
    combined = pd.concat([raw, calibrated], ignore_index=True)
    summary_rows: list[dict[str, object]] = []
    season_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []
    for method, subset in combined.groupby("method"):
        summary_rows.append(
            {
                "method": method,
                **evaluate_quantiles(subset["actual"], subset, target, config.model.quantiles),
            }
        )
        for season, group in subset.groupby("season"):
            season_rows.append(
                {
                    "method": method,
                    "season": int(season),
                    "rows": len(group),
                    **evaluate_quantiles(group["actual"], group, target, config.model.quantiles),
                }
            )
        for position, group in subset.groupby("position"):
            position_rows.append(
                {
                    "method": method,
                    "position": position,
                    "rows": len(group),
                    **evaluate_quantiles(group["actual"], group, target, config.model.quantiles),
                }
            )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "predictions": write_table(combined, output_dir / f"{target}_conformal_predictions.csv"),
        "summary": write_table(
            pd.DataFrame(summary_rows), output_dir / f"{target}_conformal_summary.csv"
        ),
        "season_metrics": write_table(
            pd.DataFrame(season_rows), output_dir / f"{target}_conformal_season_metrics.csv"
        ),
        "position_metrics": write_table(
            pd.DataFrame(position_rows), output_dir / f"{target}_conformal_position_metrics.csv"
        ),
        "quantile_calibration": write_table(
            quantile_calibration_table(combined, target, config.model.quantiles),
            output_dir / f"{target}_conformal_quantile_calibration.csv",
        ),
        "interval_calibration": write_table(
            interval_calibration_table(combined, target),
            output_dir / f"{target}_conformal_interval_calibration.csv",
        ),
        "corrections": write_table(diagnostics, output_dir / f"{target}_conformal_corrections.csv"),
    }


def train_opportunity_workflow(
    features_path: str | Path,
    model_path: str | Path,
    predictions_path: str | Path,
    config: EngineConfig,
    holdout_season: int | None = None,
) -> dict[str, Path]:
    from player_state_engine.models.opportunity import OpportunityHeadBundle

    frame = read_table(features_path)
    actual = frame.loc[~frame.get("is_projection_row", False).astype(bool)].copy()
    seasons = sorted(int(s) for s in actual["season"].unique())
    if len(seasons) < 2:
        raise ValueError(
            "Opportunity training requires at least two seasons for temporal cross-fitting."
        )
    test_season = holdout_season or seasons[-1]
    train = actual.loc[actual["season"] < test_season]
    test = actual.loc[actual["season"] == test_season]
    if train.empty or test.empty:
        raise ValueError("The requested opportunity holdout split is empty.")
    base = feature_columns(
        train, targets=tuple(column for column in train if column.startswith("opportunity_"))
    )
    # Intelligence is evaluated separately; opportunity heads begin with numerical and objective context.
    base = [
        column for column in base if not column.startswith(("availability_", "news_", "persona_"))
    ]
    bundle = OpportunityHeadBundle(config.model).fit(train, base)
    model = bundle.save(model_path)
    predictions = bundle.predict(test)
    for target in bundle.stage_targets.values():
        for name in target:
            if name in test:
                predictions[f"actual_{name}"] = test[name].to_numpy()
    return {
        "model": model,
        "predictions": write_table(predictions, predictions_path),
    }


def intelligence_ablation_workflow(
    features_path: str | Path,
    target: str,
    output_dir: str | Path,
    config: EngineConfig,
) -> dict[str, Path]:
    from player_state_engine.evaluation.ablations import (
        run_intelligence_ablation_benchmark,
        summarize_ablation_runs,
    )

    frame = read_table(features_path)
    base = [
        column
        for column in feature_columns_for_target(frame, target)
        if not column.startswith(("availability_", "news_", "persona_"))
    ]
    runs = run_intelligence_ablation_benchmark(
        frame,
        base,
        target,
        replace(config.model, targets=(target,)),
        output_dir=output_dir,
        min_train_weeks=config.benchmark.min_train_weeks,
        retrain_every_weeks=config.benchmark.retrain_every_weeks,
        rolling_window=config.benchmark.rolling_window,
        seed=config.random_seed,
    )
    summary = summarize_ablation_runs(runs)
    output_dir = Path(output_dir)
    paths = {"summary": write_table(summary, output_dir / "ablation_summary.csv")}
    season_parts: list[pd.DataFrame] = []
    for name, run in runs.items():
        engine = run.result.season_metrics.loc[
            run.result.season_metrics["method"] == "quantile_engine"
        ].copy()
        engine["ablation"] = name
        season_parts.append(engine)
    if season_parts:
        paths["season_metrics"] = write_table(
            pd.concat(season_parts, ignore_index=True), output_dir / "ablation_season_metrics.csv"
        )
    return paths
