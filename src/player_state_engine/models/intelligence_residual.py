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


def _pipeline(
    frame: pd.DataFrame,
    features: list[str],
    *,
    loss: str = "squared_error",
    quantile: float | None = None,
) -> Pipeline:
    numeric = [column for column in features if pd.api.types.is_numeric_dtype(frame[column].dtype)]
    categorical = [column for column in features if column not in numeric]
    transformers: list[tuple[str, object, list[str]]] = []
    if numeric:
        transformers.append(
            ("numeric", SimpleImputer(strategy="median", add_indicator=True), numeric)
        )
    if categorical:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        (
                            "encode",
                            OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
                        ),
                    ]
                ),
                categorical,
            )
        )
    kwargs: dict[str, object] = {
        "loss": loss,
        "max_iter": 120,
        "learning_rate": 0.04,
        "max_leaf_nodes": 15,
        "min_samples_leaf": 40,
        "l2_regularization": 3.0,
        "random_state": 42,
    }
    if quantile is not None:
        kwargs["quantile"] = quantile
    return Pipeline(
        [
            ("preprocess", ColumnTransformer(transformers, remainder="drop")),
            ("model", HistGradientBoostingRegressor(**kwargs)),
        ]
    )


@dataclass(slots=True)
class ResidualAdjustmentConfig:
    max_center_shift_fraction: float = 0.25
    min_width_scale: float = 0.85
    max_width_scale: float = 1.15


class IntelligenceResidualAdjuster:
    """Small, auditable correction layer over frozen numerical predictions.

    It must be trained on out-of-sample baseline predictions. Intelligence can
    alter the center by only a fraction of the baseline interval width and can
    widen/narrow uncertainty only within configured bounds.
    """

    def __init__(self, config: ResidualAdjustmentConfig | None = None) -> None:
        self.config = config or ResidualAdjustmentConfig()
        self.target: str | None = None
        self.features: list[str] = []
        self.center_model: Pipeline | None = None
        self.width_model: Pipeline | None = None

    def fit(
        self,
        frame: pd.DataFrame,
        baseline_predictions: pd.DataFrame,
        target: str,
        features: Iterable[str],
    ) -> IntelligenceResidualAdjuster:
        self.target = target
        self.features = list(features)
        if not self.features:
            raise ValueError("At least one intelligence feature is required.")
        for column in self.features:
            if column not in frame:
                raise ValueError(f"Missing intelligence feature {column!r}.")
        q10, q50, q90 = (f"{target}_q10", f"{target}_q50", f"{target}_q90")
        required = {q10, q50, q90, "actual"}
        missing = required - set(baseline_predictions.columns)
        if missing:
            raise ValueError(f"Baseline predictions missing columns: {sorted(missing)}")
        if len(frame) != len(baseline_predictions):
            raise ValueError("Feature and baseline prediction rows must align exactly.")

        data = frame.reset_index(drop=True).copy()
        pred = baseline_predictions.reset_index(drop=True)
        center = pd.to_numeric(pred[q50], errors="coerce")
        half_width = (
            pd.to_numeric(pred[q90], errors="coerce") - pd.to_numeric(pred[q10], errors="coerce")
        ).clip(lower=1e-3) / 2.0
        residual = pd.to_numeric(pred["actual"], errors="coerce") - center
        data["_center_residual"] = residual
        data["_log_width_ratio"] = np.log1p(residual.abs() / half_width)

        self.center_model = _pipeline(data, self.features)
        self.center_model.fit(data[self.features], data["_center_residual"])
        self.width_model = _pipeline(data, self.features)
        self.width_model.fit(data[self.features], data["_log_width_ratio"])
        return self

    def transform(self, frame: pd.DataFrame, baseline_predictions: pd.DataFrame) -> pd.DataFrame:
        if self.target is None or self.center_model is None or self.width_model is None:
            raise RuntimeError("IntelligenceResidualAdjuster has not been fitted.")
        if len(frame) != len(baseline_predictions):
            raise ValueError("Feature and baseline prediction rows must align exactly.")
        target = self.target
        q10, q50, q90 = (f"{target}_q10", f"{target}_q50", f"{target}_q90")
        output = baseline_predictions.reset_index(drop=True).copy()
        features = frame.reset_index(drop=True)[self.features]
        low = pd.to_numeric(output[q10], errors="coerce").to_numpy(float)
        median = pd.to_numeric(output[q50], errors="coerce").to_numpy(float)
        high = pd.to_numeric(output[q90], errors="coerce").to_numpy(float)
        half_width = np.maximum((high - low) / 2.0, 1e-3)

        raw_shift = self.center_model.predict(features)
        cap = self.config.max_center_shift_fraction * half_width
        shift = np.clip(raw_shift, -cap, cap)
        raw_width_signal = self.width_model.predict(features)
        width_scale = np.clip(
            np.exp(raw_width_signal - np.nanmedian(raw_width_signal)),
            self.config.min_width_scale,
            self.config.max_width_scale,
        )
        new_median = median + shift
        new_low = new_median - width_scale * (median - low)
        new_high = new_median + width_scale * (high - median)
        output[[q10, q50, q90]] = np.sort(np.vstack([new_low, new_median, new_high]), axis=0).T
        output["intelligence_center_shift"] = shift
        output["intelligence_width_scale"] = width_scale
        output["intelligence_modifier_applied"] = 1
        return output

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> IntelligenceResidualAdjuster:
        model = joblib.load(path)
        if not isinstance(model, cls):
            raise TypeError("Saved object is not an IntelligenceResidualAdjuster.")
        return model
