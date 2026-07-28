from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder


@dataclass(slots=True)
class RookieProjectionConfig:
    quantiles: tuple[float, ...] = (0.1, 0.5, 0.9)
    minimum_training_rows: int = 100
    analog_count: int = 10


class RookieProjectionModel:
    """Draft-capital and athletic-prior model for players with no NFL history."""

    def __init__(self, config: RookieProjectionConfig | None = None) -> None:
        self.config = config or RookieProjectionConfig()
        self.features: list[str] = []
        self.target = "rookie_fantasy_points_ppr"
        self.models: dict[float, Pipeline] = {}
        self.training_frame: pd.DataFrame | None = None

    def _pipeline(self, frame: pd.DataFrame, quantile: float) -> Pipeline:
        numeric = [c for c in self.features if pd.api.types.is_numeric_dtype(frame[c])]
        categorical = [c for c in self.features if c not in numeric]
        transformers = []
        if numeric:
            transformers.append(
                ("num", SimpleImputer(strategy="median", add_indicator=True), numeric)
            )
        if categorical:
            transformers.append(
                (
                    "cat",
                    Pipeline(
                        [
                            ("impute", SimpleImputer(strategy="most_frequent")),
                            (
                                "encode",
                                OrdinalEncoder(
                                    handle_unknown="use_encoded_value", unknown_value=-1
                                ),
                            ),
                        ]
                    ),
                    categorical,
                )
            )
        return Pipeline(
            [
                ("pre", ColumnTransformer(transformers, remainder="drop")),
                (
                    "model",
                    HistGradientBoostingRegressor(
                        loss="quantile",
                        quantile=quantile,
                        max_iter=180,
                        learning_rate=0.035,
                        max_leaf_nodes=15,
                        min_samples_leaf=25,
                        l2_regularization=5.0,
                        random_state=42,
                    ),
                ),
            ]
        )

    def fit(
        self,
        frame: pd.DataFrame,
        features: Iterable[str],
        target: str = "rookie_fantasy_points_ppr",
    ) -> RookieProjectionModel:
        self.features = list(features)
        self.target = target
        usable = frame.loc[pd.to_numeric(frame[target], errors="coerce").notna()].copy()
        if len(usable) < self.config.minimum_training_rows:
            raise ValueError(
                f"Rookie model requires at least {self.config.minimum_training_rows} rows."
            )
        self.models = {}
        for q in self.config.quantiles:
            model = self._pipeline(usable, q)
            model.fit(usable[self.features], usable[target])
            self.models[q] = model
        self.training_frame = usable[
            [*self.features, target, "player_name", "position", "draft_year"]
        ].copy()
        return self

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        if not self.models:
            raise RuntimeError("RookieProjectionModel is not fitted.")
        context = [c for c in ("player_name", "position", "draft_year", "draft_team") if c in frame]
        out = frame[context].copy()
        for q, model in self.models.items():
            out[f"{self.target}_q{int(q * 100):02d}"] = np.maximum(
                model.predict(frame[self.features]), 0.0
            )
        qcols = [f"{self.target}_q{int(q * 100):02d}" for q in self.config.quantiles]
        out[qcols] = np.sort(out[qcols].to_numpy(), axis=1)
        return out

    def analogs(self, row: pd.Series, count: int | None = None) -> pd.DataFrame:
        if self.training_frame is None:
            raise RuntimeError("RookieProjectionModel is not fitted.")
        count = count or self.config.analog_count
        training = self.training_frame.copy()
        numeric = [c for c in self.features if pd.api.types.is_numeric_dtype(training[c])]
        scale = training[numeric].std().replace(0, 1)
        distance = ((training[numeric] - row[numeric]) / scale).pow(2).mean(axis=1).pow(0.5)
        same_position = training["position"].eq(row.get("position"))
        training["analog_distance"] = distance + (~same_position).astype(float) * 2.0
        return training.nsmallest(count, "analog_distance")

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        return path
