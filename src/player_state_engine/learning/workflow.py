from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from player_state_engine.config import EngineConfig
from player_state_engine.data.io import read_table, write_table
from player_state_engine.evaluation.benchmark import run_multiseason_benchmark
from player_state_engine.evaluation.metrics import evaluate_quantiles
from player_state_engine.evaluation.reporting import persist_benchmark
from player_state_engine.features.weekly import feature_columns_for_target
from player_state_engine.learning.gates import evaluate_benchmark_gate
from player_state_engine.learning.registry import (
    ModelRecord,
    load_registry,
    promote_model,
    register_model,
    save_registry,
)
from player_state_engine.models.conformal import (
    TargetPositionConformalCalibrator,
    apply_earlier_season_conformal,
)
from player_state_engine.models.hybrid import HybridQuantileModelBundle


def continual_update(
    features_path: str | Path,
    target: str,
    registry_path: str | Path,
    output_dir: str | Path,
    config: EngineConfig,
    force: bool = False,
) -> ModelRecord | None:
    """Train a guarded expanding-window challenger when new completed weeks arrive.

    This is continual batch learning, not uncontrolled online gradient updates.
    Every challenger must re-run temporal baseline and calibration gates.
    """

    frame = read_table(features_path)
    mask = (
        ~frame["is_projection_row"].astype(bool)
        if "is_projection_row" in frame
        else pd.Series(True, index=frame.index)
    )
    actual = frame.loc[mask].copy()
    actual["fold_week"] = actual["season"] * 25 + actual["week"]
    latest_fold = int(actual["fold_week"].max())
    registry = load_registry(registry_path)
    previous = registry.latest_for_target(target)
    new_weeks = latest_fold - previous.training_end_fold_week if previous else 10**9
    if not force and new_weeks < config.continual_learning.min_new_completed_weeks:
        return None

    output_dir = Path(output_dir)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    model_id = hashlib.sha256(f"{target}|{latest_fold}|{stamp}".encode()).hexdigest()[:12]
    candidate_dir = output_dir / target / model_id
    candidate_dir.mkdir(parents=True, exist_ok=True)

    features = feature_columns_for_target(actual, target)
    benchmark = run_multiseason_benchmark(
        actual,
        features,
        target,
        config=replace(config.model, targets=(target,)),
        min_train_weeks=config.benchmark.min_train_weeks,
        retrain_every_weeks=config.benchmark.retrain_every_weeks,
        rolling_window=config.benchmark.rolling_window,
    )
    benchmark_paths = persist_benchmark(benchmark, target, candidate_dir / "benchmark")

    calibrated_predictions, conformal_diagnostics = apply_earlier_season_conformal(
        benchmark.predictions,
        target,
        config.model.quantiles,
        minimum_calibration_seasons=config.conformal.minimum_calibration_seasons,
        min_group_rows=config.conformal.min_group_rows,
        shrinkage_rows=config.conformal.shrinkage_rows,
    )
    calibrated_summary_row = {
        "method": "quantile_engine",
        **evaluate_quantiles(
            calibrated_predictions["actual"], calibrated_predictions, target, config.model.quantiles
        ),
    }
    calibrated_summary = pd.concat(
        [
            pd.DataFrame([calibrated_summary_row]),
            benchmark.summary_metrics.loc[benchmark.summary_metrics["method"] != "quantile_engine"],
        ],
        ignore_index=True,
    )
    position_rows: list[dict[str, object]] = []
    for position, subset in calibrated_predictions.groupby("position"):
        position_rows.append(
            {
                "method": "quantile_engine",
                "position": position,
                "rows": len(subset),
                **evaluate_quantiles(subset["actual"], subset, target, config.model.quantiles),
            }
        )
    calibrated_position = pd.concat(
        [
            pd.DataFrame(position_rows),
            benchmark.position_metrics.loc[
                benchmark.position_metrics["method"] != "quantile_engine"
            ],
        ],
        ignore_index=True,
    )
    write_table(
        calibrated_predictions, candidate_dir / "benchmark" / f"{target}_conformal_predictions.csv"
    )
    write_table(
        conformal_diagnostics, candidate_dir / "benchmark" / f"{target}_conformal_corrections.csv"
    )
    write_table(
        calibrated_summary, candidate_dir / "benchmark" / f"{target}_conformal_gate_summary.csv"
    )
    decision = evaluate_benchmark_gate(
        calibrated_summary,
        calibrated_position,
        config.continual_learning,
    )

    bundle = HybridQuantileModelBundle(replace(config.model, targets=(target,))).fit(
        actual, features, (target,)
    )
    final_calibrator = TargetPositionConformalCalibrator(
        quantiles=config.model.quantiles,
        min_group_rows=config.conformal.min_group_rows,
        shrinkage_rows=config.conformal.shrinkage_rows,
    ).fit(
        benchmark.predictions,
        target,
        method="quantile_engine",
        through_season=int(actual["season"].max()),
    )
    bundle.set_calibrator(target, final_calibrator)
    model_path = bundle.save(candidate_dir / "model.joblib")
    record = ModelRecord(
        model_id=model_id,
        target=target,
        training_end_fold_week=latest_fold,
        model_path=str(model_path),
        metrics_path=str(benchmark_paths["summary_metrics"]),
        benchmark_path=str(benchmark_paths["report"]),
        status="approved" if decision.approved else "rejected",
        metrics=decision.metrics,
        gate_reasons=decision.reasons,
        metadata={
            "feature_count": len(features),
            "continual_mode": "expanding_window_batch",
            "calibration": "target_position_earlier_season_conformal",
            "calibrator_embedded": True,
        },
    )
    register_model(registry, record)
    if decision.approved and config.continual_learning.auto_promote:
        promote_model(registry, model_id)
    save_registry(registry, registry_path)
    return record
