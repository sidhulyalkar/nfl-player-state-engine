from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from player_state_engine.fantasy.draft_market import (
    _binary_metrics,
    _draft_room_bootstrap,
    _eligible_rows,
    _market_verified_rate,
    chronological_room_holdout,
    draft_format_key,
    empirical_adp_bucket_baseline,
    normal_adp_baseline,
)
from player_state_engine.fantasy.draft_survival import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    _pipeline,
    prepare_survival_features,
)

SUPPLY_FEATURES = (
    "position_market_rank",
    "position_supply_to_next",
    "position_supply_next_round",
    "draft_market_depth",
)


def prepare_supply_features(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(SUPPLY_FEATURES) - set(frame.columns))
    if missing:
        raise ValueError(f"Supply ablation requires timestamp-safe market fields: {missing}")

    prepared = prepare_survival_features(frame)
    for name in SUPPLY_FEATURES:
        prepared[name] = pd.to_numeric(frame[name], errors="coerce").to_numpy()
    return prepared


def _validate_supply_support(train: pd.DataFrame, test: pd.DataFrame) -> None:
    for name in SUPPLY_FEATURES:
        train_values = pd.to_numeric(train[name], errors="coerce")
        test_values = pd.to_numeric(test[name], errors="coerce")
        if not np.isfinite(train_values.to_numpy(dtype=float, na_value=np.nan)).any():
            raise ValueError(f"Supply feature {name!r} has no finite training values")
        if not np.isfinite(test_values.to_numpy(dtype=float, na_value=np.nan)).any():
            raise ValueError(f"Supply feature {name!r} has no finite holdout values")


def _supply_pipeline() -> Pipeline:
    numeric_features = list(NUMERIC_FEATURES + SUPPLY_FEATURES)
    numeric = Pipeline(
        steps=[("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]
    )
    categorical = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("one_hot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    transform = ColumnTransformer(
        transformers=[
            ("numeric", numeric, numeric_features),
            ("categorical", categorical, list(CATEGORICAL_FEATURES)),
        ]
    )
    return Pipeline(
        steps=[
            ("features", transform),
            (
                "classifier",
                LogisticRegression(C=0.75, max_iter=2000, solver="liblinear", random_state=42),
            ),
        ]
    )


def evaluate_supply_feature_ablation(
    observations: pd.DataFrame,
    *,
    min_rows: int = 250,
    min_drafts: int = 5,
    test_fraction: float = 0.20,
    min_holdout_drafts: int = 5,
    min_brier_improvement: float = 0.001,
    max_ece_regression: float = 0.02,
    min_format_rows: int = 50,
    max_format_brier_regression: float = 0.005,
    min_draft_consistency: float = 0.60,
    bootstrap_samples: int = 2000,
    require_verified_market: bool = True,
    random_state: int = 42,
) -> dict[str, Any]:
    """Evaluate timestamp-safe room-supply features without changing live model authority."""

    data, target = _eligible_rows(observations)
    drafts = data["draft_id"].astype(str)
    n_drafts = int(drafts.nunique())
    if len(data) < int(min_rows):
        raise ValueError(f"Need at least {int(min_rows)} eligible rows; received {len(data)}.")
    if n_drafts < int(min_drafts):
        raise ValueError(f"Need at least {int(min_drafts)} independent drafts; received {n_drafts}.")
    if target.nunique() < 2:
        raise ValueError("Supply ablation target must contain both survival outcomes.")
    if not 0.0 <= float(min_draft_consistency) <= 1.0:
        raise ValueError("min_draft_consistency must be between 0 and 1")

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
        raise ValueError("Supply ablation holdout must contain both survival outcomes.")
    _validate_supply_support(train, test)

    base_pipeline = _pipeline()
    base_pipeline.fit(prepare_survival_features(train), train_y)
    base_probability = np.clip(
        base_pipeline.predict_proba(prepare_survival_features(test))[:, 1],
        1e-6,
        1.0 - 1e-6,
    )

    supply_pipeline = _supply_pipeline()
    supply_pipeline.fit(prepare_supply_features(train), train_y)
    supply_probability = np.clip(
        supply_pipeline.predict_proba(prepare_supply_features(test))[:, 1],
        1e-6,
        1.0 - 1e-6,
    )

    normal_probability = np.clip(normal_adp_baseline(test), 1e-6, 1.0 - 1e-6)
    bucket_probability = empirical_adp_bucket_baseline(train, train_y, test)

    base_metrics = _binary_metrics(test_y, base_probability)
    supply_metrics = _binary_metrics(test_y, supply_probability)
    normal_metrics = _binary_metrics(test_y, normal_probability)
    bucket_metrics = _binary_metrics(test_y, bucket_probability)
    baseline_name, baseline_metrics = min(
        (("normal_adp", normal_metrics), ("empirical_adp_bucket", bucket_metrics)),
        key=lambda item: item[1]["brier"],
    )

    incremental_brier_improvement = float(base_metrics["brier"] - supply_metrics["brier"])
    simple_baseline_improvement = float(baseline_metrics["brier"] - supply_metrics["brier"])
    bootstrap = _draft_room_bootstrap(
        test,
        supply_probability,
        base_probability,
        test_y,
        samples=bootstrap_samples,
        seed=random_state,
    )

    format_key = draft_format_key(test).reset_index(drop=True)
    format_rows: list[dict[str, Any]] = []
    format_regressions: list[str] = []
    for key in sorted(format_key.unique()):
        mask = format_key.eq(key).to_numpy()
        rows = int(mask.sum())
        if rows < int(min_format_rows):
            continue
        truth_slice = test_y.loc[mask]
        base_slice = _binary_metrics(truth_slice, base_probability[mask])
        supply_slice = _binary_metrics(truth_slice, supply_probability[mask])
        regression = float(supply_slice["brier"] - base_slice["brier"])
        format_rows.append(
            {
                "format_key": str(key),
                "rows": rows,
                "base_brier": base_slice["brier"],
                "supply_brier": supply_slice["brier"],
                "brier_regression_vs_base": regression,
                "base_ece": base_slice["ece"],
                "supply_ece": supply_slice["ece"],
            }
        )
        if regression > float(max_format_brier_regression):
            format_regressions.append(str(key))

    market_verified_rate = _market_verified_rate(data)
    blockers: list[str] = []
    if incremental_brier_improvement < float(min_brier_improvement):
        blockers.append("supply_incremental_brier_improvement_below_gate")
    if simple_baseline_improvement < float(min_brier_improvement):
        blockers.append("supply_brier_improvement_vs_simple_baseline_below_gate")
    if bootstrap.ci_low <= 0.0:
        blockers.append("supply_incremental_brier_ci_not_positive")
    if bootstrap.room_consistency < float(min_draft_consistency):
        blockers.append("supply_draft_room_consistency_below_gate")
    if float(supply_metrics["ece"]) > float(base_metrics["ece"]) + float(max_ece_regression):
        blockers.append("supply_calibration_regression")
    if format_regressions:
        blockers.append("supply_format_slice_brier_regression")
    if require_verified_market and market_verified_rate < 1.0:
        blockers.append("point_in_time_market_not_fully_verified")
    blockers = list(dict.fromkeys(blockers))

    return {
        "schema_version": 1,
        "authority": "research_challenger_only",
        "experiment": "draft_market_supply_feature_ablation",
        "live_authority_changed": False,
        "automatic_promotion": False,
        "feature_family": list(SUPPLY_FEATURES),
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
        "base_model": base_metrics,
        "supply_challenger": supply_metrics,
        "simple_baselines": {
            "normal_adp": normal_metrics,
            "empirical_adp_bucket": bucket_metrics,
            "best_by_brier": baseline_name,
        },
        "incremental_brier_improvement": incremental_brier_improvement,
        "brier_improvement_vs_best_simple_baseline": simple_baseline_improvement,
        "paired_draft_room_bootstrap": {
            "effect": bootstrap.effect,
            "ci_low": bootstrap.ci_low,
            "ci_high": bootstrap.ci_high,
            "probability_improves": bootstrap.probability_improves,
            "p_value": bootstrap.p_value,
            "room_consistency": bootstrap.room_consistency,
            "rooms": bootstrap.rooms,
            "samples": bootstrap.samples,
        },
        "format_slices": format_rows,
        "next_stage": {
            "eligible_for_downstream_replay": not blockers,
            "blockers": blockers,
            "meaning": (
                "A clear result only authorizes testing this feature family in frozen decision replay; "
                "it does not authorize live draft-market promotion."
            ),
            "gates": {
                "min_brier_improvement": float(min_brier_improvement),
                "max_ece_regression": float(max_ece_regression),
                "min_format_rows": int(min_format_rows),
                "max_format_brier_regression": float(max_format_brier_regression),
                "min_draft_consistency": float(min_draft_consistency),
                "bootstrap_ci_low_must_be_positive": True,
                "require_verified_market": bool(require_verified_market),
            },
        },
    }
