from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from player_state_engine.config import ModelConfig

TARGET_POSITIONS: dict[str, set[str]] = {
    "fantasy_points_ppr": {"QB", "RB", "WR", "TE"},
    "targets": {"RB", "WR", "TE"},
    "receptions": {"RB", "WR", "TE"},
    "receiving_yards": {"RB", "WR", "TE"},
    "carries": {"QB", "RB", "WR"},
    "rushing_yards": {"QB", "RB", "WR"},
    "passing_yards": {"QB"},
    "passing_attempts": {"QB"},
    "opportunity_snap_share": {"QB", "RB", "WR", "TE"},
    "opportunity_route_participation": {"RB", "WR", "TE"},
    "opportunity_team_plays": {"QB", "RB", "WR", "TE"},
    "opportunity_team_dropbacks": {"QB", "RB", "WR", "TE"},
    "opportunity_carry_share": {"QB", "RB", "WR"},
    "opportunity_target_share": {"RB", "WR", "TE"},
    "opportunity_red_zone_share": {"QB", "RB", "WR", "TE"},
    "opportunity_total_touchdowns": {"QB", "RB", "WR", "TE"},
}

NONNEGATIVE_TARGETS = set(TARGET_POSITIONS)


def _make_pipeline(
    frame: pd.DataFrame, features: list[str], quantile: float, config: ModelConfig
) -> Pipeline:
    numeric = [column for column in features if pd.api.types.is_numeric_dtype(frame[column].dtype)]
    categorical = [column for column in features if column not in numeric]

    transformers: list[tuple[str, object, list[str]]] = []
    if numeric:
        transformers.append(
            ("numeric", SimpleImputer(strategy="median", add_indicator=True), numeric)
        )
    if categorical:
        categorical_pipe = Pipeline(
            [
                ("impute", SimpleImputer(strategy="most_frequent")),
                (
                    "encode",
                    OrdinalEncoder(
                        handle_unknown="use_encoded_value",
                        unknown_value=-1,
                        encoded_missing_value=-2,
                    ),
                ),
            ]
        )
        transformers.append(("categorical", categorical_pipe, categorical))

    preprocessor = ColumnTransformer(
        transformers=transformers, remainder="drop", verbose_feature_names_out=False
    )
    estimator = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=quantile,
        max_iter=config.max_iter,
        learning_rate=config.learning_rate,
        max_leaf_nodes=config.max_leaf_nodes,
        min_samples_leaf=config.min_samples_leaf,
        l2_regularization=config.l2_regularization,
        random_state=config.random_seed,
    )
    return Pipeline([("preprocess", preprocessor), ("model", estimator)])


class QuantileModelBundle:
    """One leakage-safe quantile model per target and requested quantile."""

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or ModelConfig()
        self.features: list[str] = []
        self.targets: list[str] = []
        self.models: dict[str, dict[float, Pipeline]] = {}
        self.training_summary: dict[str, dict[str, object]] = {}

    def fit(
        self,
        frame: pd.DataFrame,
        features: Iterable[str],
        targets: Iterable[str] | None = None,
    ) -> QuantileModelBundle:
        self.features = list(features)
        requested = list(targets or self.config.targets)
        self.targets = [target for target in requested if target in frame.columns]
        if not self.features:
            raise ValueError("No feature columns were supplied.")
        if not self.targets:
            raise ValueError("None of the requested targets exist in the training frame.")

        for target in self.targets:
            eligible = TARGET_POSITIONS.get(target)
            subset = frame.loc[~frame[target].isna()].copy()
            if eligible and "position" in subset.columns:
                subset = subset.loc[subset["position"].isin(eligible)]
            if len(subset) < 25:
                raise ValueError(
                    f"Target {target!r} has only {len(subset)} eligible rows; at least 25 are required."
                )

            self.models[target] = {}
            for quantile in self.config.quantiles:
                pipeline = _make_pipeline(subset, self.features, quantile, self.config)
                pipeline.fit(subset[self.features], subset[target].astype(float))
                self.models[target][float(quantile)] = pipeline
            self.training_summary[target] = {
                "rows": len(subset),
                "positions": sorted(eligible) if eligible else "all",
                "target_mean": float(subset[target].mean()),
                "target_std": float(subset[target].std(ddof=0)),
            }
        return self

    def predict(self, frame: pd.DataFrame, include_context: bool = True) -> pd.DataFrame:
        if not self.models:
            raise RuntimeError("Model bundle has not been fitted.")
        missing = [feature for feature in self.features if feature not in frame.columns]
        if missing:
            raise ValueError(
                f"Prediction frame is missing {len(missing)} features; first missing: {missing[:5]}"
            )

        context_columns = [
            column
            for column in (
                "season",
                "week",
                "game_id",
                "player_id",
                "player_name",
                "recent_team",
                "opponent_team",
                "position",
            )
            if column in frame.columns
        ]
        output = (
            frame[context_columns].copy() if include_context else pd.DataFrame(index=frame.index)
        )

        for target, quantile_models in self.models.items():
            eligible = TARGET_POSITIONS.get(target)
            target_predictions: list[np.ndarray] = []
            ordered_quantiles = sorted(quantile_models)
            for quantile in ordered_quantiles:
                values = quantile_models[quantile].predict(frame[self.features]).astype(float)
                if eligible and "position" in frame.columns:
                    values = np.where(frame["position"].isin(eligible), values, 0.0)
                if target in NONNEGATIVE_TARGETS:
                    values = np.clip(values, 0.0, None)
                target_predictions.append(values)

            # Enforce monotonic quantiles in case independently fitted models cross.
            monotonic = np.sort(np.vstack(target_predictions), axis=0)
            for i, quantile in enumerate(ordered_quantiles):
                label = int(round(quantile * 100))
                output[f"{target}_q{label:02d}"] = monotonic[i]
        return output.reset_index(drop=True)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "config": asdict(self.config),
            "features": self.features,
            "targets": self.targets,
            "models": self.models,
            "training_summary": self.training_summary,
        }
        joblib.dump(payload, path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> QuantileModelBundle:
        payload = joblib.load(path)
        config = ModelConfig(**payload["config"])
        bundle = cls(config=config)
        bundle.features = list(payload["features"])
        bundle.targets = list(payload["targets"])
        bundle.models = payload["models"]
        bundle.training_summary = payload.get("training_summary", {})
        return bundle
