from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.state_graph.experiments import (
    EvidenceTier,
    ExperimentLedger,
    ExperimentRecord,
    PromotionPolicy,
    consistency_rate,
    paired_block_bootstrap,
)

CANONICAL_KEYS = ("target", "method", "player_id", "season", "week")
PAIR_KEYS = ("target", "player_id", "season", "week")


@dataclass(slots=True)
class EvidenceBundle:
    """Canonical frozen benchmark outputs for model comparison and promotion review."""

    predictions: pd.DataFrame
    method_summary: pd.DataFrame
    slice_metrics: pd.DataFrame
    paired_comparisons: pd.DataFrame
    experiment_ledger: pd.DataFrame


def _column_for_quantile(frame: pd.DataFrame, target: str, quantile: int) -> str:
    canonical = f"q{quantile}"
    target_specific = f"{target}_q{quantile}"
    if canonical in frame:
        return canonical
    if target_specific in frame:
        return target_specific
    raise ValueError(
        f"Prediction artifact missing q{quantile}; expected {canonical!r} or {target_specific!r}"
    )


def _canonical_identity_column(frame: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    numeric = values.to_numpy(dtype=float)
    if not bool(np.isfinite(numeric).all()):
        raise ValueError(f"Prediction artifact has non-finite {column} identity values")
    if not bool(np.equal(numeric, np.floor(numeric)).all()):
        raise ValueError(f"Prediction artifact has non-integer {column} identity values")
    return values.astype("Int64")


def canonicalize_predictions(
    frame: pd.DataFrame,
    *,
    target: str,
    method: str | None = None,
    source: str = "benchmark",
    actual_column: str = "actual",
) -> pd.DataFrame:
    """Convert a frozen prediction artifact into the Evidence Factory row contract.

    The function is intentionally strict about identity. Duplicate player-week-method rows are
    rejected because they would otherwise create many-to-many paired comparisons and silently
    distort evidence.
    """

    required = {"player_id", "season", "week"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"Prediction artifact missing identity columns: {sorted(missing)}")
    if actual_column not in frame:
        raise ValueError(f"Prediction artifact missing actual outcome column: {actual_column}")
    if method is None and "method" not in frame:
        raise ValueError("Prediction artifact needs a method column or an explicit method override")
    if not str(target).strip():
        raise ValueError("Prediction target cannot be blank")

    raw_player_ids = frame["player_id"]
    if bool(raw_player_ids.isna().any()) or bool(raw_player_ids.astype(str).str.strip().eq("").any()):
        raise ValueError("Prediction artifact has missing player_id identity values")

    q10_column = _column_for_quantile(frame, target, 10)
    q50_column = _column_for_quantile(frame, target, 50)
    q90_column = _column_for_quantile(frame, target, 90)

    output = pd.DataFrame(index=frame.index)
    output["target"] = str(target)
    output["method"] = str(method) if method is not None else frame["method"].astype(str)
    if bool(output["method"].str.strip().isin({"", "nan", "None", "<NA>"}).any()):
        raise ValueError("Prediction artifact has missing method identity values")
    output["source"] = str(source)
    output["player_id"] = raw_player_ids.astype(str)
    output["season"] = _canonical_identity_column(frame, "season")
    output["week"] = _canonical_identity_column(frame, "week")
    output["position"] = (
        frame["position"].astype(str).str.upper() if "position" in frame else "UNKNOWN"
    )
    for column in ("player_name", "recent_team", "team", "opponent_team", "opponent"):
        if column in frame:
            output[column] = frame[column]
    output["prediction_cutoff"] = frame.get("prediction_cutoff", pd.Series(None, index=frame.index))
    output["actual"] = pd.to_numeric(frame[actual_column], errors="coerce")
    output["q10"] = pd.to_numeric(frame[q10_column], errors="coerce")
    output["q50"] = pd.to_numeric(frame[q50_column], errors="coerce")
    output["q90"] = pd.to_numeric(frame[q90_column], errors="coerce")

    finite = np.ones(len(output), dtype=bool)
    for column in ("actual", "q10", "q50", "q90"):
        finite &= np.isfinite(pd.to_numeric(output[column], errors="coerce").to_numpy(dtype=float))
    output["valid_prediction"] = finite
    output["crossed_quantiles"] = (output["q10"] > output["q50"]) | (
        output["q50"] > output["q90"]
    )
    output["forecast_id"] = (
        output["target"].astype(str)
        + "|"
        + output["method"].astype(str)
        + "|"
        + output["player_id"].astype(str)
        + "|"
        + output["season"].astype(str)
        + "|"
        + output["week"].astype(str)
    )

    duplicates = output.duplicated(list(CANONICAL_KEYS), keep=False)
    if duplicates.any():
        examples = output.loc[duplicates, list(CANONICAL_KEYS)].head(5).to_dict("records")
        raise ValueError(f"Duplicate canonical prediction rows detected: {examples}")
    return output.sort_values(list(CANONICAL_KEYS), kind="mergesort").reset_index(drop=True)


def _pinball(actual: pd.Series, prediction: pd.Series, quantile: float) -> pd.Series:
    residual = actual - prediction
    return pd.Series(
        np.maximum(quantile * residual, (quantile - 1.0) * residual),
        index=actual.index,
    )


def add_row_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    """Attach per-player-week loss, coverage, sharpness, and validity diagnostics."""

    required = {*CANONICAL_KEYS, "actual", "q10", "q50", "q90", "valid_prediction"}
    missing = required - set(predictions)
    if missing:
        raise ValueError(f"Canonical predictions missing columns: {sorted(missing)}")
    output = predictions.copy()
    actual = pd.to_numeric(output["actual"], errors="coerce")
    q10 = pd.to_numeric(output["q10"], errors="coerce")
    q50 = pd.to_numeric(output["q50"], errors="coerce")
    q90 = pd.to_numeric(output["q90"], errors="coerce")
    output["pinball_q10"] = _pinball(actual, q10, 0.10)
    output["pinball_q50"] = _pinball(actual, q50, 0.50)
    output["pinball_q90"] = _pinball(actual, q90, 0.90)
    output["mean_pinball"] = output[["pinball_q10", "pinball_q50", "pinball_q90"]].mean(
        axis=1
    )
    output["absolute_q50_error"] = (actual - q50).abs()
    output["signed_q50_error"] = q50 - actual
    output["covered_80"] = ((actual >= q10) & (actual <= q90)).astype(float)
    output["interval_width_80"] = q90 - q10
    invalid = ~output["valid_prediction"].astype(bool)
    metric_columns = [
        "pinball_q10",
        "pinball_q50",
        "pinball_q90",
        "mean_pinball",
        "absolute_q50_error",
        "signed_q50_error",
        "covered_80",
        "interval_width_80",
    ]
    output.loc[invalid, metric_columns] = np.nan
    return output


def _metric_row(frame: pd.DataFrame, **labels: object) -> dict[str, object]:
    valid = frame.loc[frame["valid_prediction"].astype(bool)].copy()
    if valid.empty:
        return {
            **labels,
            "rows": 0,
            "available_rows": int(len(frame)),
            "valid_rate": 0.0,
        }
    return {
        **labels,
        "rows": int(len(valid)),
        "available_rows": int(len(frame)),
        "valid_rate": float(len(valid) / max(len(frame), 1)),
        "mean_pinball": float(valid["mean_pinball"].mean()),
        "pinball_q10": float(valid["pinball_q10"].mean()),
        "pinball_q50": float(valid["pinball_q50"].mean()),
        "pinball_q90": float(valid["pinball_q90"].mean()),
        "q50_mae": float(valid["absolute_q50_error"].mean()),
        "q50_bias": float(valid["signed_q50_error"].mean()),
        "empirical_80_coverage": float(valid["covered_80"].mean()),
        "coverage_gap": float(valid["covered_80"].mean() - 0.80),
        "mean_interval_width_80": float(valid["interval_width_80"].mean()),
        "crossed_quantile_rate": float(valid["crossed_quantiles"].astype(float).mean()),
    }


def summarize_methods(predictions: pd.DataFrame) -> pd.DataFrame:
    measured = add_row_metrics(predictions)
    rows = [
        _metric_row(group, target=str(target), method=str(method))
        for (target, method), group in measured.groupby(["target", "method"], sort=True)
    ]
    return pd.DataFrame(rows)


def summarize_slices(predictions: pd.DataFrame) -> pd.DataFrame:
    """Return one long-form table for the required season/position/week diagnostics."""

    measured = add_row_metrics(predictions)
    rows: list[dict[str, object]] = []
    for (target, method), model_rows in measured.groupby(["target", "method"], sort=True):
        rows.append(_metric_row(model_rows, target=target, method=method, scope="overall"))
        for season, group in model_rows.groupby("season", dropna=False, sort=True):
            rows.append(
                _metric_row(group, target=target, method=method, scope="season", season=season)
            )
        for position, group in model_rows.groupby("position", dropna=False, sort=True):
            rows.append(
                _metric_row(
                    group,
                    target=target,
                    method=method,
                    scope="position",
                    position=position,
                )
            )
        for (position, season), group in model_rows.groupby(
            ["position", "season"], dropna=False, sort=True
        ):
            rows.append(
                _metric_row(
                    group,
                    target=target,
                    method=method,
                    scope="position_season",
                    position=position,
                    season=season,
                )
            )
        for (season, week), group in model_rows.groupby(
            ["season", "week"], dropna=False, sort=True
        ):
            rows.append(
                _metric_row(
                    group,
                    target=target,
                    method=method,
                    scope="week",
                    season=season,
                    week=week,
                )
            )
    return pd.DataFrame(rows)


def _paired_rows(
    predictions: pd.DataFrame,
    *,
    target: str,
    champion_method: str,
    challenger_method: str,
) -> tuple[pd.DataFrame, float]:
    measured = add_row_metrics(predictions)
    champion = measured.loc[
        measured["target"].eq(target) & measured["method"].eq(champion_method)
    ].copy()
    challenger = measured.loc[
        measured["target"].eq(target) & measured["method"].eq(challenger_method)
    ].copy()
    if champion.empty:
        raise ValueError(f"Champion method {champion_method!r} is unavailable for target {target!r}")
    if challenger.empty:
        raise ValueError(
            f"Challenger method {challenger_method!r} is unavailable for target {target!r}"
        )

    champion = champion.loc[champion["valid_prediction"].astype(bool)].copy()
    challenger = challenger.loc[challenger["valid_prediction"].astype(bool)].copy()
    paired = champion.merge(
        challenger,
        on=list(PAIR_KEYS),
        how="inner",
        suffixes=("_champion", "_challenger"),
        validate="one_to_one",
    )
    if paired.empty:
        raise ValueError(
            f"No paired frozen observations for {champion_method!r} vs {challenger_method!r}"
        )
    actual_delta = (
        pd.to_numeric(paired["actual_champion"], errors="coerce")
        - pd.to_numeric(paired["actual_challenger"], errors="coerce")
    ).abs()
    if bool((actual_delta > 1e-9).any()):
        raise ValueError("Paired prediction artifacts disagree on the realized outcome")

    champion_position = paired["position_champion"].astype(str)
    challenger_position = paired["position_challenger"].astype(str)
    known = ~champion_position.eq("UNKNOWN") & ~challenger_position.eq("UNKNOWN")
    if bool((known & ~champion_position.eq(challenger_position)).any()):
        raise ValueError("Paired prediction artifacts disagree on player position")
    paired["position"] = champion_position.where(~champion_position.eq("UNKNOWN"), challenger_position)
    paired["actual"] = pd.to_numeric(paired["actual_champion"], errors="coerce")
    paired["effect"] = paired["mean_pinball_champion"] - paired["mean_pinball_challenger"]
    denominator = max(1, min(len(champion), len(challenger)))
    overlap = min(1.0, len(paired) / denominator)
    return paired, float(overlap)


def compare_methods(
    predictions: pd.DataFrame,
    *,
    target: str,
    champion_method: str,
    challenger_method: str,
    experiment_id: str | None = None,
    bootstrap_samples: int = 2000,
    seed: int = 42,
    negative_control_passed: bool = False,
    downstream_decision_effect: float | None = None,
    calibration_tolerance: float = 0.05,
    promotion_policy: PromotionPolicy | None = None,
) -> tuple[dict[str, object], ExperimentRecord]:
    """Create one paired champion/challenger evidence record on identical player-weeks."""

    paired, overlap = _paired_rows(
        predictions,
        target=target,
        champion_method=champion_method,
        challenger_method=challenger_method,
    )
    bootstrap = None
    try:
        bootstrap = paired_block_bootstrap(
            paired,
            champion_column="mean_pinball_champion",
            challenger_column="mean_pinball_challenger",
            bootstrap_samples=bootstrap_samples,
            seed=seed,
        )
    except ValueError:
        pass

    effect = float(paired["effect"].mean()) if bootstrap is None else bootstrap.effect
    ci_low = float("nan") if bootstrap is None else bootstrap.ci_low
    ci_high = float("nan") if bootstrap is None else bootstrap.ci_high
    seasons = int(pd.to_numeric(paired["season"], errors="coerce").nunique())
    tier = (
        EvidenceTier.MULTI_SEASON_ISOLATED
        if seasons >= 2
        else EvidenceTier.SINGLE_HISTORICAL_SLICE
    )
    record = ExperimentRecord(
        experiment_id=experiment_id or f"{target}:{challenger_method}:vs:{champion_method}",
        challenger=challenger_method,
        champion=champion_method,
        primary_metric="mean_pinball",
        evidence_tier=tier,
        effect=effect,
        ci_low=ci_low,
        ci_high=ci_high,
        season_consistency=consistency_rate(
            paired, effect_column="effect", group_columns=("season",)
        ),
        position_consistency=consistency_rate(
            paired, effect_column="effect", group_columns=("position",)
        ),
        week_consistency=consistency_rate(
            paired, effect_column="effect", group_columns=("season", "week")
        ),
        coverage=overlap,
        data_availability=overlap,
        negative_control_passed=negative_control_passed,
        downstream_decision_effect=downstream_decision_effect,
    )
    (promotion_policy or PromotionPolicy()).evaluate(record)

    champion_coverage = float(paired["covered_80_champion"].mean())
    challenger_coverage = float(paired["covered_80_challenger"].mean())
    challenger_crossed = float(paired["crossed_quantiles_challenger"].astype(float).mean())
    if abs(challenger_coverage - 0.80) > calibration_tolerance:
        record.blockers.append("challenger_interval_coverage_outside_tolerance")
    if challenger_crossed > 0.0:
        record.blockers.append("challenger_crossed_quantiles")
    record.blockers = list(dict.fromkeys(record.blockers))
    record.promoted = not record.blockers

    payload = {
        "experiment_id": record.experiment_id,
        "target": target,
        "champion": champion_method,
        "challenger": challenger_method,
        "paired_rows": int(len(paired)),
        "paired_seasons": seasons,
        "overlap_rate": overlap,
        "champion_mean_pinball": float(paired["mean_pinball_champion"].mean()),
        "challenger_mean_pinball": float(paired["mean_pinball_challenger"].mean()),
        "pinball_effect_champion_minus_challenger": effect,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "probability_improves": (
            float(bootstrap.probability_improves) if bootstrap is not None else float("nan")
        ),
        "champion_q50_mae": float(paired["absolute_q50_error_champion"].mean()),
        "challenger_q50_mae": float(paired["absolute_q50_error_challenger"].mean()),
        "champion_80_coverage": champion_coverage,
        "challenger_80_coverage": challenger_coverage,
        "champion_mean_width_80": float(paired["interval_width_80_champion"].mean()),
        "challenger_mean_width_80": float(paired["interval_width_80_challenger"].mean()),
        "challenger_crossed_quantile_rate": challenger_crossed,
        "season_consistency": record.season_consistency,
        "position_consistency": record.position_consistency,
        "week_consistency": record.week_consistency,
        "evidence_tier": int(record.evidence_tier),
        "promotion_status": "eligible" if record.promoted else "blocked",
        "blockers": "|".join(record.blockers),
    }
    return payload, record


def build_evidence_bundle(
    prediction_frames: Iterable[pd.DataFrame],
    *,
    champion_method: str = "quantile_engine",
    challenger_methods: Iterable[str] | None = None,
    bootstrap_samples: int = 2000,
    seed: int = 42,
    negative_control_methods: Iterable[str] = (),
    calibration_tolerance: float = 0.05,
) -> EvidenceBundle:
    """Build one canonical evidence ledger across targets and model families."""

    pieces = [frame.copy() for frame in prediction_frames if not frame.empty]
    if not pieces:
        raise ValueError("Evidence Factory received no prediction rows")
    predictions = pd.concat(pieces, ignore_index=True, sort=False)
    duplicate_mask = predictions.duplicated(list(CANONICAL_KEYS), keep=False)
    if duplicate_mask.any():
        examples = predictions.loc[duplicate_mask, list(CANONICAL_KEYS)].head(5).to_dict(
            "records"
        )
        raise ValueError(f"Duplicate rows after combining prediction artifacts: {examples}")

    methods_requested = set(challenger_methods or ())
    negative_controls = set(negative_control_methods)
    comparison_rows: list[dict[str, object]] = []
    ledger = ExperimentLedger()
    for target, target_rows in predictions.groupby("target", sort=True):
        available_methods = sorted(set(target_rows["method"].astype(str)))
        challengers = (
            [method for method in available_methods if method in methods_requested]
            if methods_requested
            else [method for method in available_methods if method != champion_method]
        )
        if champion_method not in available_methods:
            continue
        for offset, challenger in enumerate(challengers):
            row, record = compare_methods(
                predictions,
                target=str(target),
                champion_method=champion_method,
                challenger_method=challenger,
                bootstrap_samples=bootstrap_samples,
                seed=seed + offset * 1009,
                negative_control_passed=challenger in negative_controls,
                calibration_tolerance=calibration_tolerance,
            )
            comparison_rows.append(row)
            ledger.add(record)

    return EvidenceBundle(
        predictions=predictions.sort_values(list(CANONICAL_KEYS), kind="mergesort").reset_index(
            drop=True
        ),
        method_summary=summarize_methods(predictions),
        slice_metrics=summarize_slices(predictions),
        paired_comparisons=pd.DataFrame(comparison_rows),
        experiment_ledger=ledger.to_frame(),
    )
