from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import mean_pinball_loss

QUANTILES = (0.10, 0.50, 0.90)


@dataclass(frozen=True, slots=True)
class ConformalQualificationGate:
    """Frozen production-uncertainty criteria for q10/q50/q90 preseason distributions."""

    nominal_interval_coverage: float = 0.80
    overall_coverage_tolerance: float = 0.04
    min_position_coverage: float = 0.70
    max_position_coverage: float = 0.90
    max_overall_pinball_regression_pct: float = 2.0
    max_position_pinball_regression_pct: float = 3.0
    max_q50_abs_bias_worsening_points: float = 2.0


@dataclass(frozen=True, slots=True)
class ConformalQualificationDecision:
    approved: bool
    blockers: tuple[str, ...]
    metrics: dict[str, float]
    policy: dict[str, float]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _qcol(target: str, quantile: float) -> str:
    return f"{target}_q{int(round(float(quantile) * 100)):02d}"


def _metrics(
    frame: pd.DataFrame,
    *,
    target: str,
    method: str,
    group: str | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    grouped = [("ALL", frame)] if group is None else frame.groupby(group, dropna=False, sort=True)
    for key, subset in grouped:
        actual = pd.to_numeric(subset["actual"], errors="coerce").to_numpy(float)
        predictions = {
            quantile: pd.to_numeric(subset[_qcol(target, quantile)], errors="coerce").to_numpy(float)
            for quantile in QUANTILES
        }
        valid = np.isfinite(actual)
        for values in predictions.values():
            valid &= np.isfinite(values)
        if not valid.any():
            continue
        losses = [
            mean_pinball_loss(actual[valid], predictions[q][valid], alpha=q) for q in QUANTILES
        ]
        q10 = predictions[0.10]
        q50 = predictions[0.50]
        q90 = predictions[0.90]
        rows.append(
            {
                "method": method,
                "group": str(key),
                "rows": int(valid.sum()),
                "mean_pinball": float(np.mean(losses)),
                "interval_coverage": float(
                    np.mean((actual[valid] >= q10[valid]) & (actual[valid] <= q90[valid]))
                ),
                "q50_bias": float(np.mean(q50[valid] - actual[valid])),
                "q50_mae": float(np.mean(np.abs(q50[valid] - actual[valid]))),
            }
        )
    return pd.DataFrame(rows)


def _regression_pct(raw: float, calibrated: float) -> float:
    if raw <= 0.0:
        return float("inf") if calibrated > raw else 0.0
    return 100.0 * (calibrated - raw) / raw


def qualify_conformal_predictions(
    raw: pd.DataFrame,
    calibrated: pd.DataFrame,
    *,
    target: str,
    policy: ConformalQualificationGate | None = None,
) -> tuple[ConformalQualificationDecision, pd.DataFrame, pd.DataFrame]:
    """Compare earlier-season conformal predictions with their exact raw held-out rows.

    Only rows for which a calibrator was fit from strictly earlier seasons are eligible. The
    comparison is paired by season/player identity and uses the same frozen policy as the original
    preseason uncertainty qualification.
    """

    gate = policy or ConformalQualificationGate()
    required = {
        "season",
        "player_id",
        "position",
        "actual",
        *(_qcol(target, q) for q in QUANTILES),
    }
    missing_raw = required - set(raw)
    missing_calibrated = (required | {"conformal_applied"}) - set(calibrated)
    if missing_raw:
        raise ValueError(f"Raw uncertainty frame missing columns: {sorted(missing_raw)}")
    if missing_calibrated:
        raise ValueError(
            f"Calibrated uncertainty frame missing columns: {sorted(missing_calibrated)}"
        )

    applied = pd.to_numeric(calibrated["conformal_applied"], errors="coerce").fillna(0).eq(1)
    calibrated_eval = calibrated.loc[applied].copy()
    if calibrated_eval.empty:
        raise ValueError("No conformal-evaluable seasons remain")
    if calibrated_eval.duplicated(["season", "player_id"]).any():
        raise ValueError("Calibrated uncertainty rows contain duplicate season/player identities")

    keys = calibrated_eval[["season", "player_id"]].drop_duplicates()
    raw_eval = raw.merge(keys, on=["season", "player_id"], how="inner", validate="one_to_one")
    if len(raw_eval) != len(calibrated_eval):
        raise ValueError("Raw/calibrated conformal evaluation rows do not pair one-to-one")

    overall = pd.concat(
        [
            _metrics(raw_eval, target=target, method="raw"),
            _metrics(calibrated_eval, target=target, method="conformal"),
        ],
        ignore_index=True,
    )
    positions = pd.concat(
        [
            _metrics(raw_eval, target=target, method="raw", group="position"),
            _metrics(calibrated_eval, target=target, method="conformal", group="position"),
        ],
        ignore_index=True,
    )
    if overall.empty or set(overall["method"]) != {"raw", "conformal"}:
        raise ValueError("Conformal qualification produced incomplete overall metrics")
    if positions.empty:
        raise ValueError("Conformal qualification produced no position metrics")

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
        "evaluable_rows": float(len(calibrated_eval)),
    }

    blockers: list[str] = []
    lower = gate.nominal_interval_coverage - gate.overall_coverage_tolerance
    upper = gate.nominal_interval_coverage + gate.overall_coverage_tolerance
    coverage = metrics["conformal_overall_coverage"]
    if coverage < lower or coverage > upper:
        blockers.append("OVERALL_INTERVAL_COVERAGE_OUTSIDE_TOLERANCE")
    if metrics["overall_pinball_regression_pct"] > gate.max_overall_pinball_regression_pct:
        blockers.append("OVERALL_PINBALL_REGRESSION")
    if metrics["q50_abs_bias_worsening_points"] > gate.max_q50_abs_bias_worsening_points:
        blockers.append("Q50_BIAS_WORSENED")

    calibrated_positions = positions.loc[positions["method"].eq("conformal")]
    raw_positions = positions.loc[positions["method"].eq("raw")]
    for _, row in calibrated_positions.iterrows():
        position = str(row["group"])
        position_coverage = float(row["interval_coverage"])
        metrics[f"position_{position}_coverage"] = position_coverage
        if (
            position_coverage < gate.min_position_coverage
            or position_coverage > gate.max_position_coverage
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
        if regression > gate.max_position_pinball_regression_pct:
            blockers.append(f"POSITION_PINBALL_REGRESSION:{position}")

    decision = ConformalQualificationDecision(
        approved=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        metrics=metrics,
        policy=asdict(gate),
    )
    return decision, overall, positions
