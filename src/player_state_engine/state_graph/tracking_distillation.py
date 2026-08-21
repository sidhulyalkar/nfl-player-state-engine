from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.multioutput import MultiOutputRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


@dataclass(slots=True)
class TrackingTeacherDistiller:
    """Distill scarce tracking-derived teacher signals into live-available proxy features.

    Raw tracking is deliberately a research teacher rather than a production dependency. The
    distiller only emits proxy estimates for teacher concepts that can be reconstructed from
    point-in-time production features.
    """

    alpha: float = 5.0
    feature_columns: tuple[str, ...] = ()
    teacher_columns: tuple[str, ...] = ()
    model: Pipeline | None = field(default=None, repr=False)

    def fit(
        self,
        frame: pd.DataFrame,
        *,
        feature_columns: tuple[str, ...],
        teacher_columns: tuple[str, ...],
    ) -> TrackingTeacherDistiller:
        missing = (set(feature_columns) | set(teacher_columns)) - set(frame)
        if missing:
            raise ValueError(f"Tracking distillation missing columns: {sorted(missing)}")
        work = frame[list(feature_columns) + list(teacher_columns)].apply(
            pd.to_numeric, errors="coerce"
        ).dropna()
        if len(work) < 100:
            raise ValueError("Tracking distillation requires at least 100 complete rows")
        self.feature_columns = tuple(feature_columns)
        self.teacher_columns = tuple(teacher_columns)
        estimator = MultiOutputRegressor(Ridge(alpha=max(float(self.alpha), 1e-6)))
        self.model = Pipeline([("scale", StandardScaler()), ("ridge", estimator)])
        self.model.fit(work[list(self.feature_columns)], work[list(self.teacher_columns)])
        return self

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        if self.model is None:
            raise RuntimeError("Tracking distiller must be fitted before transform")
        missing = set(self.feature_columns) - set(frame)
        if missing:
            raise ValueError(f"Tracking proxy frame missing columns: {sorted(missing)}")
        features = frame[list(self.feature_columns)].apply(pd.to_numeric, errors="coerce")
        if features.isna().any().any():
            raise ValueError("Tracking proxy features must be complete")
        prediction = np.asarray(self.model.predict(features), dtype=float)
        out = frame.copy()
        for index, teacher in enumerate(self.teacher_columns):
            out[f"tracking_proxy__{teacher}"] = prediction[:, index]
        out["tracking_proxy_source"] = "tracking_teacher_distillation_v1"
        return out
