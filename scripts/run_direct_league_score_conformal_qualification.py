from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from player_state_engine.data.io import read_table, write_table
from player_state_engine.evaluation.uncertainty_qualification import (
    ConformalQualificationGate,
    qualify_conformal_predictions,
)
from player_state_engine.fantasy.preseason_league_score import LEAGUE_SCORE_TARGET
from player_state_engine.learning.artifact_registry import sha256_file
from player_state_engine.models.conformal import (
    TargetPositionConformalCalibrator,
    apply_earlier_season_conformal,
)

RAW_METHOD = "preseason_quantile_engine"
QUANTILES = (0.10, 0.50, 0.90)


def _target_frame(predictions: pd.DataFrame) -> pd.DataFrame:
    required = {
        "season",
        "player_id",
        "position",
        "target",
        "method",
        "actual",
        "prediction_q10",
        "prediction_q50",
        "prediction_q90",
    }
    missing = required - set(predictions)
    if missing:
        raise ValueError(f"Direct league-score predictions missing columns: {sorted(missing)}")
    data = predictions.loc[
        predictions["target"].eq(LEAGUE_SCORE_TARGET) & predictions["method"].eq(RAW_METHOD)
    ].copy()
    if data.empty:
        raise ValueError("Direct benchmark contains no league-score quantile-engine rows")
    return data.rename(
        columns={
            "prediction_q10": f"{LEAGUE_SCORE_TARGET}_q10",
            "prediction_q50": f"{LEAGUE_SCORE_TARGET}_q50",
            "prediction_q90": f"{LEAGUE_SCORE_TARGET}_q90",
        }
    ).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Apply the already-registered earlier-season conformal policy separately to each "
            "direct preseason league-score benchmark."
        )
    )
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    benchmark_manifest_path = args.benchmark_root / "qualification.json"
    benchmark_manifest = json.loads(benchmark_manifest_path.read_text(encoding="utf-8"))
    if benchmark_manifest.get("authority") != "direct_league_score_research_only":
        raise RuntimeError("Input is not a direct league-score benchmark artifact")
    if benchmark_manifest.get("automatic_promotion") is not False:
        raise RuntimeError("Direct benchmark authority contract is invalid")

    policy = ConformalQualificationGate()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, object] = {}

    for slug, league_meta in sorted((benchmark_manifest.get("leagues") or {}).items()):
        gate = league_meta.get("gate") or {}
        if gate.get("approved") is not True or gate.get("blockers") not in ([], ()): 
            raise RuntimeError(f"Direct benchmark gate is not approved for {slug}")

        predictions_path = args.benchmark_root / slug / "predictions.parquet"
        predictions = read_table(predictions_path)
        raw = _target_frame(predictions)
        calibrated, diagnostics = apply_earlier_season_conformal(
            raw,
            LEAGUE_SCORE_TARGET,
            method=RAW_METHOD,
            minimum_calibration_seasons=1,
            min_group_rows=75,
            shrinkage_rows=200.0,
        )
        decision, overall, positions = qualify_conformal_predictions(
            raw,
            calibrated,
            target=LEAGUE_SCORE_TARGET,
            policy=policy,
        )

        league_output = args.output_dir / slug
        league_output.mkdir(parents=True, exist_ok=True)
        write_table(calibrated, league_output / "calibrated_predictions.parquet")
        write_table(diagnostics, league_output / "calibration_diagnostics.csv")
        write_table(overall, league_output / "overall_metrics.csv")
        write_table(positions, league_output / "position_metrics.csv")
        (league_output / "qualification.json").write_text(
            json.dumps(decision.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        # Fit the candidate production calibrator only from historical out-of-sample engine
        # predictions. This artifact remains research-only here and is usable by a 2026 challenger
        # only if the separate decision above is approved and later cited by exact digest.
        final_calibrator = TargetPositionConformalCalibrator(
            quantiles=QUANTILES,
            min_group_rows=75,
            shrinkage_rows=200.0,
        ).fit(
            raw,
            LEAGUE_SCORE_TARGET,
            method=RAW_METHOD,
            through_season=int(pd.to_numeric(raw["season"], errors="coerce").max()),
        )
        calibrator_path = final_calibrator.save(league_output / "calibrator.joblib")
        write_table(
            final_calibrator.diagnostics_frame(),
            league_output / "final_calibrator_diagnostics.csv",
        )

        results[slug] = {
            "league_path": league_meta.get("league_path"),
            "scoring": league_meta.get("scoring"),
            "median_scoring": bool(league_meta.get("median_scoring", False)),
            "median_scoring_in_uncertainty_gate": False,
            "direct_benchmark_gate_approved": True,
            "direct_predictions_sha256": sha256_file(predictions_path),
            "decision": decision.as_dict(),
            "calibrator": {
                "sha256": sha256_file(calibrator_path),
                "fitted_through_season": final_calibrator.fitted_through_season,
                "training_authority": "historical_out_of_sample_predictions_only",
                "production_eligible_if_decision_approved": bool(decision.approved),
            },
        }

    manifest = {
        "schema_version": 1,
        "authority": "direct_league_score_uncertainty_research_only",
        "automatic_promotion": False,
        "benchmark_manifest_sha256": sha256_file(benchmark_manifest_path),
        "benchmark_source_artifacts": benchmark_manifest.get("source_artifacts"),
        "target": LEAGUE_SCORE_TARGET,
        "raw_method": RAW_METHOD,
        "calibration_contract": "each held-out season calibrated from strictly earlier seasons",
        "policy_origin": "same frozen criteria as preseason conformal qualification v0.17",
        "leagues": results,
    }
    (args.output_dir / "qualification.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
