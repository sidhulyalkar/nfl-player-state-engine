from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_pinball_loss

from player_state_engine.data.io import read_table, write_table
from player_state_engine.models.conformal import apply_earlier_season_conformal

TARGET = "fantasy_points_ppr"
QUANTILES = (0.10, 0.50, 0.90)
RAW_METHOD = "preseason_quantile_engine"


@dataclass(frozen=True, slots=True)
class PreseasonConformalGate:
    nominal_interval_coverage: float = 0.80
    overall_coverage_tolerance: float = 0.04
    min_position_coverage: float = 0.70
    max_position_coverage: float = 0.90
    max_overall_pinball_regression_pct: float = 2.0
    max_position_pinball_regression_pct: float = 3.0
    max_q50_abs_bias_worsening_points: float = 2.0


@dataclass(frozen=True, slots=True)
class PreseasonConformalDecision:
    approved: bool
    blockers: tuple[str, ...]
    metrics: dict[str, float]
    policy: dict[str, float]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


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
        raise ValueError(f"Preseason predictions missing columns: {sorted(missing)}")
    data = predictions.loc[
        predictions["target"].eq(TARGET) & predictions["method"].eq(RAW_METHOD)
    ].copy()
    if data.empty:
        raise ValueError("Frozen preseason predictions contain no PPR quantile-engine rows")
    return data.rename(
        columns={
            "prediction_q10": f"{TARGET}_q10",
            "prediction_q50": f"{TARGET}_q50",
            "prediction_q90": f"{TARGET}_q90",
        }
    ).reset_index(drop=True)


def _metrics(frame: pd.DataFrame, *, method: str, group: str | None = None) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    grouped = [("ALL", frame)] if group is None else frame.groupby(group, dropna=False, sort=True)
    for key, subset in grouped:
        actual = pd.to_numeric(subset["actual"], errors="coerce").to_numpy(float)
        losses: list[float] = []
        for quantile in QUANTILES:
            label = int(round(quantile * 100))
            prediction = pd.to_numeric(
                subset[f"{TARGET}_q{label:02d}"], errors="coerce"
            ).to_numpy(float)
            losses.append(mean_pinball_loss(actual, prediction, alpha=quantile))
        q10 = pd.to_numeric(subset[f"{TARGET}_q10"], errors="coerce").to_numpy(float)
        q50 = pd.to_numeric(subset[f"{TARGET}_q50"], errors="coerce").to_numpy(float)
        q90 = pd.to_numeric(subset[f"{TARGET}_q90"], errors="coerce").to_numpy(float)
        valid = np.isfinite(actual) & np.isfinite(q10) & np.isfinite(q50) & np.isfinite(q90)
        rows.append(
            {
                "method": method,
                "group": str(key),
                "rows": int(valid.sum()),
                "mean_pinball": float(np.mean(losses)),
                "interval_coverage": float(np.mean((actual[valid] >= q10[valid]) & (actual[valid] <= q90[valid]))),
                "q50_bias": float(np.mean(q50[valid] - actual[valid])),
                "q50_mae": float(np.mean(np.abs(q50[valid] - actual[valid]))),
            }
        )
    return pd.DataFrame(rows)


def _regression_pct(raw: float, calibrated: float) -> float:
    if raw <= 0.0:
        return float("inf") if calibrated > raw else 0.0
    return 100.0 * (calibrated - raw) / raw


def _evaluate(
    raw: pd.DataFrame,
    calibrated: pd.DataFrame,
    *,
    policy: PreseasonConformalGate,
) -> tuple[PreseasonConformalDecision, pd.DataFrame, pd.DataFrame]:
    applied = pd.to_numeric(calibrated["conformal_applied"], errors="coerce").fillna(0).eq(1)
    calibrated_eval = calibrated.loc[applied].copy()
    if calibrated_eval.empty:
        raise ValueError("No conformal-evaluable seasons remain")
    keys = calibrated_eval[["season", "player_id"]].drop_duplicates()
    raw_eval = raw.merge(keys, on=["season", "player_id"], how="inner", validate="one_to_one")

    overall = pd.concat(
        [
            _metrics(raw_eval, method="raw"),
            _metrics(calibrated_eval, method="conformal"),
        ],
        ignore_index=True,
    )
    positions = pd.concat(
        [
            _metrics(raw_eval, method="raw", group="position"),
            _metrics(calibrated_eval, method="conformal", group="position"),
        ],
        ignore_index=True,
    )

    raw_overall = overall.loc[overall["method"].eq("raw")].iloc[0]
    calibrated_overall = overall.loc[overall["method"].eq("conformal")].iloc[0]
    metrics = {
        "raw_overall_coverage": float(raw_overall["interval_coverage"]),
        "conformal_overall_coverage": float(calibrated_overall["interval_coverage"]),
        "raw_overall_pinball": float(raw_overall["mean_pinball"]),
        "conformal_overall_pinball": float(calibrated_overall["mean_pinball"]),
        "overall_pinball_regression_pct": _regression_pct(
            float(raw_overall["mean_pinball"]), float(calibrated_overall["mean_pinball"])
        ),
        "raw_q50_bias": float(raw_overall["q50_bias"]),
        "conformal_q50_bias": float(calibrated_overall["q50_bias"]),
        "q50_abs_bias_worsening_points": (
            abs(float(calibrated_overall["q50_bias"])) - abs(float(raw_overall["q50_bias"]))
        ),
        "evaluable_seasons": float(calibrated_eval["season"].nunique()),
    }

    blockers: list[str] = []
    lower = policy.nominal_interval_coverage - policy.overall_coverage_tolerance
    upper = policy.nominal_interval_coverage + policy.overall_coverage_tolerance
    coverage = metrics["conformal_overall_coverage"]
    if coverage < lower or coverage > upper:
        blockers.append("OVERALL_INTERVAL_COVERAGE_OUTSIDE_TOLERANCE")
    if metrics["overall_pinball_regression_pct"] > policy.max_overall_pinball_regression_pct:
        blockers.append("OVERALL_PINBALL_REGRESSION")
    if metrics["q50_abs_bias_worsening_points"] > policy.max_q50_abs_bias_worsening_points:
        blockers.append("Q50_BIAS_WORSENED")

    calibrated_positions = positions.loc[positions["method"].eq("conformal")]
    raw_positions = positions.loc[positions["method"].eq("raw")]
    for _, row in calibrated_positions.iterrows():
        position = str(row["group"])
        position_coverage = float(row["interval_coverage"])
        if (
            position_coverage < policy.min_position_coverage
            or position_coverage > policy.max_position_coverage
        ):
            blockers.append(f"POSITION_INTERVAL_COVERAGE:{position}")
        raw_row = raw_positions.loc[raw_positions["group"].eq(position)]
        if raw_row.empty:
            blockers.append(f"POSITION_RAW_COMPARATOR_MISSING:{position}")
            continue
        regression = _regression_pct(
            float(raw_row.iloc[0]["mean_pinball"]), float(row["mean_pinball"])
        )
        metrics[f"position_{position}_pinball_regression_pct"] = regression
        metrics[f"position_{position}_coverage"] = position_coverage
        if regression > policy.max_position_pinball_regression_pct:
            blockers.append(f"POSITION_PINBALL_REGRESSION:{position}")

    return (
        PreseasonConformalDecision(
            approved=not blockers,
            blockers=tuple(dict.fromkeys(blockers)),
            metrics=metrics,
            policy=asdict(policy),
        ),
        overall,
        positions,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a separate post-benchmark production uncertainty qualification. Each held-out "
            "season is conformal-calibrated only from earlier held-out seasons."
        )
    )
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    predictions = read_table(args.predictions)
    raw = _target_frame(predictions)
    calibrated, diagnostics = apply_earlier_season_conformal(
        raw,
        TARGET,
        method=RAW_METHOD,
        minimum_calibration_seasons=1,
        min_group_rows=75,
        shrinkage_rows=200.0,
    )
    policy = PreseasonConformalGate()
    decision, overall, positions = _evaluate(raw, calibrated, policy=policy)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_table(calibrated, args.output_dir / "calibrated_predictions.parquet")
    write_table(diagnostics, args.output_dir / "calibration_diagnostics.csv")
    write_table(overall, args.output_dir / "overall_metrics.csv")
    write_table(positions, args.output_dir / "position_metrics.csv")
    (args.output_dir / "qualification.json").write_text(
        json.dumps(decision.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(decision.as_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
