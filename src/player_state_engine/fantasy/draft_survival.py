from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from player_state_engine.fantasy.league import LeagueConfig

MODEL_VERSION = "draft-survival-logit-v1"
NUMERIC_FEATURES = (
    "current_pick",
    "next_pick",
    "picks_until_next",
    "market_adp",
    "market_adp_sd",
    "adp_minus_current",
    "adp_minus_next",
    "teams",
    "qb_slots_per_team",
    "superflex_slots_per_team",
    "starter_slots_per_team",
    "recent_position_run",
)
CATEGORICAL_FEATURES = ("position", "platform", "scoring")


@dataclass(slots=True)
class DraftSurvivalArtifact:
    pipeline: Pipeline
    version: str = MODEL_VERSION
    trained_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    rows: int = 0
    drafts: int = 0
    metrics: dict[str, float | int | str | bool] = field(default_factory=dict)
    promoted: bool = False
    promotion_reason: str = "not evaluated"
    feature_schema: tuple[str, ...] = NUMERIC_FEATURES + CATEGORICAL_FEATURES

    def save(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, destination)
        return destination

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        prepared = prepare_survival_features(frame)
        return np.asarray(self.pipeline.predict_proba(prepared)[:, 1], dtype=float)


def _numeric(frame: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name in frame:
        return pd.to_numeric(frame[name], errors="coerce").fillna(default)
    return pd.Series(default, index=frame.index, dtype=float)


def _normal_survival_probability(adp: float, pick: float, sd: float) -> float:
    if not np.isfinite(adp) or not np.isfinite(pick):
        return 0.5
    scale = max(1.0, float(sd))
    z = (float(pick) - float(adp)) / scale
    from math import erf, sqrt

    cdf = 0.5 * (1.0 + erf(z / sqrt(2.0)))
    return float(np.clip(1.0 - cdf, 0.0, 1.0))


def prepare_survival_features(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    current = _numeric(data, "current_pick")
    next_pick = _numeric(data, "next_pick")
    market_adp = _numeric(data, "market_adp", np.nan)
    market_sd = _numeric(data, "market_adp_sd", 8.0).clip(lower=1.0)
    data["current_pick"] = current
    data["next_pick"] = next_pick
    data["picks_until_next"] = _numeric(data, "picks_until_next", np.nan).fillna(
        (next_pick - current).clip(lower=0)
    )
    data["market_adp"] = market_adp
    data["market_adp_sd"] = market_sd
    data["adp_minus_current"] = _numeric(data, "adp_minus_current", np.nan).fillna(
        market_adp - current
    )
    data["adp_minus_next"] = _numeric(data, "adp_minus_next", np.nan).fillna(
        market_adp - next_pick
    )
    for name, default in (
        ("teams", 12.0),
        ("qb_slots_per_team", 1.0),
        ("superflex_slots_per_team", 0.0),
        ("starter_slots_per_team", 7.0),
        ("recent_position_run", 0.0),
    ):
        data[name] = _numeric(data, name, default)
    for name, default in (("position", "UNK"), ("platform", "unknown"), ("scoring", "unknown")):
        if name not in data:
            data[name] = default
        data[name] = data[name].fillna(default).astype(str)
    return data[list(NUMERIC_FEATURES + CATEGORICAL_FEATURES)]


def _pipeline() -> Pipeline:
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
            ("numeric", numeric, list(NUMERIC_FEATURES)),
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


def _training_target(frame: pd.DataFrame) -> pd.Series:
    if "survived_to_next_pick" in frame:
        return pd.to_numeric(frame["survived_to_next_pick"], errors="coerce").fillna(0).astype(int)
    if {"actual_pick", "next_pick"}.issubset(frame.columns):
        actual = pd.to_numeric(frame["actual_pick"], errors="coerce")
        next_pick = pd.to_numeric(frame["next_pick"], errors="coerce")
        return (actual >= next_pick).astype(int)
    raise ValueError("Training data requires survived_to_next_pick or both actual_pick and next_pick.")


def train_survival_model(
    observations: pd.DataFrame,
    *,
    min_rows: int = 250,
    min_drafts: int = 5,
    random_state: int = 42,
    min_brier_improvement: float = 0.001,
) -> DraftSurvivalArtifact:
    data = observations.copy()
    if "draft_id" not in data:
        raise ValueError("Training data requires draft_id for grouped temporal/room holdout.")
    target = _training_target(data)
    valid = target.isin([0, 1])
    if {"actual_pick", "current_pick"}.issubset(data.columns):
        actual = pd.to_numeric(data["actual_pick"], errors="coerce")
        current = pd.to_numeric(data["current_pick"], errors="coerce")
        valid &= actual > current
    data = data.loc[valid].reset_index(drop=True)
    target = target.loc[valid].reset_index(drop=True)
    drafts = data["draft_id"].astype(str)
    n_drafts = int(drafts.nunique())
    if len(data) < min_rows:
        raise ValueError(f"Need at least {min_rows} eligible rows; received {len(data)}.")
    if n_drafts < min_drafts:
        raise ValueError(f"Need at least {min_drafts} independent drafts; received {n_drafts}.")
    if target.nunique() < 2:
        raise ValueError("Training target must contain both survival outcomes.")

    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=random_state)
    train_idx, test_idx = next(splitter.split(data, target, groups=drafts))
    train_x = prepare_survival_features(data.iloc[train_idx])
    test_x = prepare_survival_features(data.iloc[test_idx])
    train_y = target.iloc[train_idx]
    test_y = target.iloc[test_idx]

    pipeline = _pipeline()
    pipeline.fit(train_x, train_y)
    probability = np.clip(pipeline.predict_proba(test_x)[:, 1], 1e-6, 1 - 1e-6)
    fallback = np.asarray(
        [
            _normal_survival_probability(adp, pick, sd)
            for adp, pick, sd in zip(
                _numeric(data.iloc[test_idx], "market_adp", np.nan),
                _numeric(data.iloc[test_idx], "next_pick", np.nan),
                _numeric(data.iloc[test_idx], "market_adp_sd", 8.0),
                strict=False,
            )
        ],
        dtype=float,
    )
    fallback = np.clip(fallback, 1e-6, 1 - 1e-6)
    model_brier = float(brier_score_loss(test_y, probability))
    fallback_brier = float(brier_score_loss(test_y, fallback))
    brier_improvement = fallback_brier - model_brier
    promoted = bool(brier_improvement >= float(min_brier_improvement))
    promotion_reason = (
        f"holdout Brier improved by {brier_improvement:.6f}"
        if promoted
        else f"holdout Brier improvement {brier_improvement:.6f} below gate {min_brier_improvement:.6f}"
    )
    metrics: dict[str, float | int | str | bool] = {
        "holdout_rows": int(len(test_idx)),
        "holdout_drafts": int(drafts.iloc[test_idx].nunique()),
        "brier": model_brier,
        "fallback_brier": fallback_brier,
        "brier_improvement": brier_improvement,
        "promotion_passed": promoted,
        "log_loss": float(log_loss(test_y, probability, labels=[0, 1])),
        "positive_rate": float(test_y.mean()),
    }
    if test_y.nunique() == 2:
        metrics["roc_auc"] = float(roc_auc_score(test_y, probability))

    pipeline.fit(prepare_survival_features(data), target)
    return DraftSurvivalArtifact(
        pipeline=pipeline,
        rows=int(len(data)),
        drafts=n_drafts,
        metrics=metrics,
        promoted=promoted,
        promotion_reason=promotion_reason,
    )


def load_survival_artifact(path: str | Path | None) -> DraftSurvivalArtifact | None:
    if not path:
        return None
    source = Path(path)
    if not source.exists():
        return None
    artifact = joblib.load(source)
    if not isinstance(artifact, DraftSurvivalArtifact):
        raise TypeError(f"Unexpected draft survival artifact type: {type(artifact)!r}")
    return artifact


def board_survival_features(
    board: pd.DataFrame,
    config: LeagueConfig,
    *,
    current_pick: int,
    next_pick: int | None,
    platform: str = "unknown",
    recent_position_runs: dict[str, int] | None = None,
) -> pd.DataFrame:
    data = pd.DataFrame(index=board.index)
    data["current_pick"] = int(current_pick)
    data["next_pick"] = int(next_pick or current_pick)
    data["market_adp"] = _numeric(board, "market_adp", np.nan)
    data["market_adp_sd"] = _numeric(board, "market_adp_sd", 8.0)
    data["teams"] = int(config.teams)
    data["position"] = board["position"].astype(str).str.upper()
    data["platform"] = platform
    data["scoring"] = config.scoring
    data["qb_slots_per_team"] = int(config.roster_slots.get("QB", 0))
    data["superflex_slots_per_team"] = sum(
        count
        for slot, count in config.flex_slots.items()
        if "QB" in config.flex_eligibility.get(slot, ())
    )
    data["starter_slots_per_team"] = sum(config.direct_starter_slots.values()) + sum(
        config.flex_slots.values()
    )
    run_map = recent_position_runs or {}
    data["recent_position_run"] = data["position"].map(run_map).fillna(0).astype(float)
    return prepare_survival_features(data)


def apply_empirical_survival(
    board: pd.DataFrame,
    artifact: DraftSurvivalArtifact | None,
    config: LeagueConfig,
    *,
    current_pick: int,
    next_pick: int | None,
    platform: str = "unknown",
    recent_position_runs: dict[str, int] | None = None,
) -> pd.DataFrame:
    data = board.copy()
    fallback = _numeric(data, "survival_to_next_pick", 0.5).clip(0, 1)
    data["survival_fallback_probability"] = fallback
    if artifact is None or data.empty or next_pick is None or not artifact.promoted:
        data["survival_model_source"] = (
            "normal_adp_fallback" if artifact is None else "normal_adp_fallback_unpromoted"
        )
        data["survival_model_version"] = "transparent-normal-v1"
        return data

    features = board_survival_features(
        data,
        config,
        current_pick=current_pick,
        next_pick=next_pick,
        platform=platform,
        recent_position_runs=recent_position_runs,
    )
    empirical = pd.Series(
        np.clip(artifact.predict_proba(features), 0.01, 0.99), index=data.index, dtype=float
    )
    old_urgency = 1.0 - fallback
    new_urgency = 1.0 - empirical
    total_weight = 1.0 if config.median_scoring else 0.96
    if "live_draft_score" in data:
        data["live_draft_score"] = (
            _numeric(data, "live_draft_score")
            + 100.0 * (0.12 / total_weight) * (new_urgency - old_urgency)
        ).clip(0, 100)
    data["survival_to_next_pick"] = empirical
    data["market_urgency"] = new_urgency
    data["survival_model_source"] = "empirical"
    data["survival_model_version"] = artifact.version

    score = _numeric(data, "live_draft_score")
    reach = _numeric(data, "reach_rounds")
    data["draft_action"] = np.select(
        [
            (score >= 82) & (empirical <= 0.45),
            score >= 72,
            (empirical >= 0.70) & (reach >= 1.0),
        ],
        ["DRAFT NOW", "TARGET", "WAIT"],
        default="CONSIDER",
    )
    tie = [column for column in ("player_id", "player_name") if column in data]
    data = data.sort_values(
        ["live_draft_score", *tie],
        ascending=[False, *([True] * len(tie))],
        kind="mergesort",
    ).reset_index(drop=True)
    data["live_rank"] = np.arange(1, len(data) + 1, dtype=int)
    return data


def artifact_metadata(artifact: DraftSurvivalArtifact | None) -> dict[str, Any]:
    if artifact is None:
        return {"available": False, "source": "normal_adp_fallback", "version": "transparent-normal-v1"}
    return {
        "available": True,
        "source": "empirical" if artifact.promoted else "normal_adp_fallback_unpromoted",
        "version": artifact.version,
        "trained_at": artifact.trained_at,
        "rows": artifact.rows,
        "drafts": artifact.drafts,
        "metrics": dict(artifact.metrics),
        "promoted": artifact.promoted,
        "promotion_reason": artifact.promotion_reason,
    }
