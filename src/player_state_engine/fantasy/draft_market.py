from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from player_state_engine.fantasy.draft_survival import (
    DraftSurvivalArtifact,
    _normal_survival_probability,
    _pipeline,
    _training_target,
    prepare_survival_features,
)

MODEL_VERSION = "draft-survival-logit-v2-chronological"
DRAFT_TIME_COLUMNS = (
    "draft_started_at",
    "draft_start",
    "draft_timestamp",
    "draft_date",
)


@dataclass(slots=True, frozen=True)
class ChronologicalSplit:
    train_index: np.ndarray
    test_index: np.ndarray
    split_kind: str
    train_drafts: tuple[str, ...]
    test_drafts: tuple[str, ...]
    train_period_end: str
    test_period_start: str


@dataclass(slots=True)
class DraftMarketTrainingResult:
    artifact: DraftSurvivalArtifact
    report: dict[str, Any]


def _numeric(frame: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name in frame:
        return pd.to_numeric(frame[name], errors="coerce").fillna(default)
    return pd.Series(default, index=frame.index, dtype=float)


def _draft_time_column(frame: pd.DataFrame) -> str | None:
    for column in DRAFT_TIME_COLUMNS:
        if column in frame and frame[column].notna().any():
            return column
    return None


def _draft_periods(frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    if "draft_id" not in frame:
        raise ValueError("Draft-market evaluation requires draft_id.")

    draft_ids = frame["draft_id"].astype(str)
    time_column = _draft_time_column(frame)
    if time_column is not None:
        parsed = pd.to_datetime(frame[time_column], errors="coerce", utc=True)
        by_draft = pd.DataFrame({"draft_id": draft_ids, "period": parsed}).groupby(
            "draft_id", sort=False
        )["period"].min()
        if by_draft.isna().any():
            missing = by_draft.index[by_draft.isna()].tolist()[:5]
            raise ValueError(
                "Draft timestamps are only partially available; cannot establish a chronological "
                f"holdout. Missing examples: {missing}"
            )
        periods = by_draft.rename("period").reset_index()
        return periods.sort_values(["period", "draft_id"], kind="mergesort"), "timestamp"

    if "season" not in frame:
        raise ValueError(
            "Chronological draft-market evaluation requires a draft timestamp or season column."
        )
    season = pd.to_numeric(frame["season"], errors="coerce")
    by_draft = pd.DataFrame({"draft_id": draft_ids, "period": season}).groupby(
        "draft_id", sort=False
    )["period"].min()
    if by_draft.isna().any():
        raise ValueError("Draft season is missing for one or more draft rooms.")
    if by_draft.nunique() < 2:
        raise ValueError(
            "Season-only draft history needs at least two seasons to establish forward transfer."
        )
    periods = by_draft.rename("period").reset_index()
    return periods.sort_values(["period", "draft_id"], kind="mergesort"), "season"


def chronological_room_holdout(
    observations: pd.DataFrame,
    *,
    test_fraction: float = 0.20,
    min_holdout_drafts: int = 2,
) -> ChronologicalSplit:
    """Hold out the latest draft rooms without allowing future rooms into training."""

    if not 0.0 < float(test_fraction) < 1.0:
        raise ValueError("test_fraction must be between 0 and 1.")
    if int(min_holdout_drafts) < 1:
        raise ValueError("min_holdout_drafts must be positive.")

    periods, split_kind = _draft_periods(observations)
    draft_count = len(periods)
    if draft_count < int(min_holdout_drafts) + 1:
        raise ValueError(
            f"Need at least {int(min_holdout_drafts) + 1} ordered drafts for chronological holdout; "
            f"received {draft_count}."
        )

    if split_kind == "season":
        ordered_periods = sorted(periods["period"].unique())
        test_periods: set[float] = set()
        target_count = max(int(min_holdout_drafts), int(ceil(draft_count * float(test_fraction))))
        running = 0
        for period in reversed(ordered_periods):
            test_periods.add(float(period))
            running += int(periods["period"].eq(period).sum())
            if running >= target_count:
                break
        test_mask = periods["period"].astype(float).isin(test_periods)
    else:
        target_count = max(int(min_holdout_drafts), int(ceil(draft_count * float(test_fraction))))
        target_count = min(target_count, draft_count - 1)
        cutoff = periods.iloc[-target_count]["period"]
        test_mask = periods["period"] >= cutoff

    test_drafts = tuple(periods.loc[test_mask, "draft_id"].astype(str))
    train_drafts = tuple(periods.loc[~test_mask, "draft_id"].astype(str))
    if not train_drafts or not test_drafts:
        raise ValueError("Chronological split produced an empty train or test partition.")

    train_period_max = periods.loc[periods["draft_id"].isin(train_drafts), "period"].max()
    test_period_min = periods.loc[periods["draft_id"].isin(test_drafts), "period"].min()
    if not bool(train_period_max < test_period_min):
        raise ValueError(
            "Chronological split could not create a strict past-to-future boundary. "
            "Provide finer draft timestamps when multiple rooms share the same coarse period."
        )

    room = observations["draft_id"].astype(str)
    train_index = np.flatnonzero(room.isin(train_drafts).to_numpy())
    test_index = np.flatnonzero(room.isin(test_drafts).to_numpy())
    return ChronologicalSplit(
        train_index=train_index,
        test_index=test_index,
        split_kind=split_kind,
        train_drafts=train_drafts,
        test_drafts=test_drafts,
        train_period_end=str(train_period_max),
        test_period_start=str(test_period_min),
    )


def draft_format_key(frame: pd.DataFrame) -> pd.Series:
    teams = _numeric(frame, "teams", 12).round().astype(int).astype(str)
    scoring = (
        frame["scoring"].fillna("unknown").astype(str).str.lower()
        if "scoring" in frame
        else pd.Series("unknown", index=frame.index)
    )
    qb = _numeric(frame, "qb_slots_per_team", 1).round().astype(int).astype(str)
    superflex = _numeric(frame, "superflex_slots_per_team", 0).round().astype(int).astype(str)
    starters = _numeric(frame, "starter_slots_per_team", 7).round().astype(int).astype(str)
    return (
        teams
        + "t|"
        + scoring
        + "|qb"
        + qb
        + "|sf"
        + superflex
        + "|start"
        + starters
    )


def expected_calibration_error(
    truth: pd.Series | np.ndarray,
    probability: np.ndarray,
    *,
    bins: int = 10,
) -> float:
    y = np.asarray(truth, dtype=float)
    p = np.asarray(probability, dtype=float)
    if len(y) == 0:
        return float("nan")
    edges = np.linspace(0.0, 1.0, int(bins) + 1)
    bucket = np.minimum(np.digitize(p, edges[1:-1], right=True), int(bins) - 1)
    total = float(len(y))
    error = 0.0
    for index in range(int(bins)):
        mask = bucket == index
        if not bool(mask.any()):
            continue
        error += float(mask.sum()) / total * abs(float(p[mask].mean()) - float(y[mask].mean()))
    return float(error)


def _binary_metrics(truth: pd.Series, probability: np.ndarray) -> dict[str, float]:
    y = np.asarray(truth, dtype=int)
    p = np.clip(np.asarray(probability, dtype=float), 1e-6, 1.0 - 1e-6)
    metrics = {
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "ece": expected_calibration_error(y, p),
        "positive_rate": float(y.mean()),
    }
    if len(np.unique(y)) == 2:
        metrics["roc_auc"] = float(roc_auc_score(y, p))
    return metrics


def normal_adp_baseline(frame: pd.DataFrame) -> np.ndarray:
    adp = _numeric(frame, "market_adp", np.nan)
    next_pick = _numeric(frame, "next_pick", np.nan)
    sd = _numeric(frame, "market_adp_sd", 8.0)
    return np.asarray(
        [
            _normal_survival_probability(a, pick, spread)
            for a, pick, spread in zip(adp, next_pick, sd, strict=False)
        ],
        dtype=float,
    )


def _bucket_frame(frame: pd.DataFrame, *, bucket_width: float) -> pd.DataFrame:
    prepared = prepare_survival_features(frame)
    output = pd.DataFrame(index=frame.index)
    output["format_key"] = draft_format_key(frame)
    output["position"] = (
        frame["position"].fillna("UNK").astype(str).str.upper()
        if "position" in frame
        else "UNK"
    )
    adp_minus_next = pd.to_numeric(prepared["adp_minus_next"], errors="coerce").fillna(0.0)
    output["adp_bucket"] = np.floor(adp_minus_next / float(bucket_width)).astype(int)
    return output


def empirical_adp_bucket_baseline(
    train_frame: pd.DataFrame,
    train_target: pd.Series,
    test_frame: pd.DataFrame,
    *,
    bucket_width: float = 4.0,
    prior_strength: float = 12.0,
) -> np.ndarray:
    """Timestamp-safe empirical survival baseline fitted only on the training partition."""

    if float(bucket_width) <= 0.0:
        raise ValueError("bucket_width must be positive.")
    if float(prior_strength) < 0.0:
        raise ValueError("prior_strength cannot be negative.")

    train_keys = _bucket_frame(train_frame, bucket_width=bucket_width)
    test_keys = _bucket_frame(test_frame, bucket_width=bucket_width)
    training = train_keys.copy()
    training["target"] = np.asarray(train_target, dtype=int)
    global_rate = float(training["target"].mean())

    def table(columns: list[str]) -> dict[tuple[object, ...], tuple[int, float]]:
        grouped = training.groupby(columns, dropna=False, sort=False)["target"].agg(["count", "sum"])
        return {
            key if isinstance(key, tuple) else (key,): (int(row["count"]), float(row["sum"]))
            for key, row in grouped.iterrows()
        }

    exact = table(["format_key", "position", "adp_bucket"])
    position_bucket = table(["position", "adp_bucket"])
    bucket_only = table(["adp_bucket"])
    probabilities: list[float] = []
    for _, row in test_keys.iterrows():
        candidates = (
            exact.get((row["format_key"], row["position"], row["adp_bucket"])),
            position_bucket.get((row["position"], row["adp_bucket"])),
            bucket_only.get((row["adp_bucket"],)),
        )
        count, successes = next((entry for entry in candidates if entry is not None), (0, 0.0))
        probability = (successes + float(prior_strength) * global_rate) / (
            count + float(prior_strength)
        )
        probabilities.append(float(np.clip(probability, 0.01, 0.99)))
    return np.asarray(probabilities, dtype=float)


def _eligible_rows(observations: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    data = observations.copy()
    target = _training_target(data)
    valid = target.isin([0, 1])
    if {"actual_pick", "current_pick"}.issubset(data.columns):
        actual = pd.to_numeric(data["actual_pick"], errors="coerce")
        current = pd.to_numeric(data["current_pick"], errors="coerce")
        valid &= actual > current
    data = data.loc[valid].reset_index(drop=True)
    target = target.loc[valid].reset_index(drop=True)
    if data.empty:
        raise ValueError("No eligible draft-market observations remain after validity filtering.")
    return data, target


def _market_verified_rate(frame: pd.DataFrame) -> float:
    if "point_in_time_market_verified" not in frame:
        return 0.0
    values = frame["point_in_time_market_verified"]
    if values.dtype == bool:
        verified = values
    else:
        verified = values.astype(str).str.lower().isin({"true", "1", "yes"})
    return float(verified.mean()) if len(frame) else 0.0


def train_chronological_survival_model(
    observations: pd.DataFrame,
    *,
    min_rows: int = 250,
    min_drafts: int = 5,
    test_fraction: float = 0.20,
    min_holdout_drafts: int = 2,
    min_brier_improvement: float = 0.001,
    max_ece_regression: float = 0.02,
    min_format_rows: int = 50,
    max_format_brier_regression: float = 0.005,
    require_verified_market: bool = True,
    random_state: int = 42,
) -> DraftMarketTrainingResult:
    """Train a draft-survival challenger under a frozen past-to-future evidence contract."""

    data, target = _eligible_rows(observations)
    drafts = data["draft_id"].astype(str)
    n_drafts = int(drafts.nunique())
    if len(data) < int(min_rows):
        raise ValueError(f"Need at least {int(min_rows)} eligible rows; received {len(data)}.")
    if n_drafts < int(min_drafts):
        raise ValueError(f"Need at least {int(min_drafts)} independent drafts; received {n_drafts}.")
    if target.nunique() < 2:
        raise ValueError("Training target must contain both survival outcomes.")

    split = chronological_room_holdout(
        data,
        test_fraction=test_fraction,
        min_holdout_drafts=min_holdout_drafts,
    )
    train = data.iloc[split.train_index].copy()
    test = data.iloc[split.test_index].copy()
    train_y = target.iloc[split.train_index].reset_index(drop=True)
    test_y = target.iloc[split.test_index].reset_index(drop=True)
    if test_y.nunique() < 2:
        raise ValueError("Chronological holdout must contain both survival outcomes.")

    pipeline = _pipeline()
    pipeline.fit(prepare_survival_features(train), train_y)
    model_probability = np.clip(
        pipeline.predict_proba(prepare_survival_features(test))[:, 1], 1e-6, 1.0 - 1e-6
    )
    normal_probability = np.clip(normal_adp_baseline(test), 1e-6, 1.0 - 1e-6)
    bucket_probability = empirical_adp_bucket_baseline(train, train_y, test)

    model_metrics = _binary_metrics(test_y, model_probability)
    normal_metrics = _binary_metrics(test_y, normal_probability)
    bucket_metrics = _binary_metrics(test_y, bucket_probability)
    baseline_name, baseline_metrics = min(
        (("normal_adp", normal_metrics), ("empirical_adp_bucket", bucket_metrics)),
        key=lambda item: item[1]["brier"],
    )
    brier_improvement = float(baseline_metrics["brier"] - model_metrics["brier"])
    best_baseline_ece = min(float(normal_metrics["ece"]), float(bucket_metrics["ece"]))

    format_key = draft_format_key(test).reset_index(drop=True)
    format_rows: list[dict[str, Any]] = []
    format_regressions: list[str] = []
    for key in sorted(format_key.unique()):
        mask = format_key.eq(key).to_numpy()
        rows = int(mask.sum())
        if rows < int(min_format_rows):
            continue
        truth_slice = test_y.loc[mask]
        model_slice = _binary_metrics(truth_slice, model_probability[mask])
        normal_slice = _binary_metrics(truth_slice, normal_probability[mask])
        bucket_slice = _binary_metrics(truth_slice, bucket_probability[mask])
        best_slice_brier = min(normal_slice["brier"], bucket_slice["brier"])
        regression = float(model_slice["brier"] - best_slice_brier)
        format_rows.append(
            {
                "format_key": str(key),
                "rows": rows,
                "model_brier": model_slice["brier"],
                "normal_adp_brier": normal_slice["brier"],
                "empirical_bucket_brier": bucket_slice["brier"],
                "brier_regression_vs_best_baseline": regression,
                "model_ece": model_slice["ece"],
            }
        )
        if regression > float(max_format_brier_regression):
            format_regressions.append(str(key))

    market_verified_rate = _market_verified_rate(data)
    blockers: list[str] = []
    if brier_improvement < float(min_brier_improvement):
        blockers.append("chronological_brier_improvement_below_gate")
    if float(model_metrics["ece"]) > best_baseline_ece + float(max_ece_regression):
        blockers.append("chronological_calibration_regression")
    if format_regressions:
        blockers.append("format_slice_brier_regression")
    if require_verified_market and market_verified_rate < 1.0:
        blockers.append("point_in_time_market_not_fully_verified")

    promoted = not blockers
    promotion_reason = (
        f"chronological Brier improved by {brier_improvement:.6f} vs {baseline_name} with all gates clear"
        if promoted
        else "blocked: " + ", ".join(blockers)
    )

    pipeline.fit(prepare_survival_features(data), target)
    artifact = DraftSurvivalArtifact(
        pipeline=pipeline,
        version=MODEL_VERSION,
        trained_at=datetime.now(UTC).isoformat(),
        rows=int(len(data)),
        drafts=n_drafts,
        metrics={
            "evaluation": "chronological_room_holdout",
            "holdout_rows": int(len(test)),
            "holdout_drafts": int(len(split.test_drafts)),
            "brier": model_metrics["brier"],
            "normal_adp_brier": normal_metrics["brier"],
            "empirical_bucket_brier": bucket_metrics["brier"],
            "best_baseline_brier": baseline_metrics["brier"],
            "best_baseline": baseline_name,
            "brier_improvement": brier_improvement,
            "log_loss": model_metrics["log_loss"],
            "ece": model_metrics["ece"],
            "best_baseline_ece": best_baseline_ece,
            "positive_rate": model_metrics["positive_rate"],
            "market_verified_rate": market_verified_rate,
            "supported_format_slices": int(len(format_rows)),
            "format_regressions": int(len(format_regressions)),
            "promotion_passed": promoted,
        },
        promoted=promoted,
        promotion_reason=promotion_reason,
    )
    if "roc_auc" in model_metrics:
        artifact.metrics["roc_auc"] = model_metrics["roc_auc"]

    report: dict[str, Any] = {
        "schema_version": 1,
        "authority": "draft_market_challenger",
        "model_version": MODEL_VERSION,
        "evaluation": {
            "split_kind": split.split_kind,
            "train_drafts": list(split.train_drafts),
            "test_drafts": list(split.test_drafts),
            "train_period_end": split.train_period_end,
            "test_period_start": split.test_period_start,
            "test_fraction": float(test_fraction),
        },
        "rows": int(len(data)),
        "drafts": n_drafts,
        "market_verified_rate": market_verified_rate,
        "model_metrics": model_metrics,
        "baselines": {
            "normal_adp": normal_metrics,
            "empirical_adp_bucket": bucket_metrics,
            "best_by_brier": baseline_name,
        },
        "format_slices": format_rows,
        "promotion": {
            "passed": promoted,
            "blockers": blockers,
            "reason": promotion_reason,
            "gates": {
                "min_brier_improvement": float(min_brier_improvement),
                "max_ece_regression": float(max_ece_regression),
                "min_format_rows": int(min_format_rows),
                "max_format_brier_regression": float(max_format_brier_regression),
                "require_verified_market": bool(require_verified_market),
            },
        },
    }
    return DraftMarketTrainingResult(artifact=artifact, report=report)
