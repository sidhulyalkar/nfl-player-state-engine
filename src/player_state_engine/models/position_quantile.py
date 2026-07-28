from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import joblib
import pandas as pd

from player_state_engine.config import ModelConfig
from player_state_engine.models.quantile import TARGET_POSITIONS, QuantileModelBundle


class PositionSpecificQuantileBundle:
    """Independent quantile bundles per position.

    This prevents zero-heavy roles from dominating a pooled conditional median.
    It is especially important for carries, where WR rows vastly outnumber RB
    rows but have a fundamentally different outcome process.
    """

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or ModelConfig()
        self.target: str | None = None
        self.features: list[str] = []
        self.models: dict[str, QuantileModelBundle] = {}

    def fit(
        self,
        frame: pd.DataFrame,
        features: Iterable[str],
        target: str,
        min_rows_per_position: int = 50,
    ) -> PositionSpecificQuantileBundle:
        self.target = target
        self.features = list(features)
        self.models = {}
        eligible = TARGET_POSITIONS.get(target)
        training_frame = frame.loc[frame["position"].isin(eligible)].copy() if eligible else frame
        for position, subset in training_frame.groupby("position", sort=True):
            if len(subset) < min_rows_per_position:
                continue
            bundle = QuantileModelBundle(self.config).fit(subset, self.features, targets=(target,))
            self.models[str(position)] = bundle
        if not self.models:
            raise ValueError("No position had enough rows to fit a position-specific model.")
        return self

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        if not self.models or self.target is None:
            raise RuntimeError("Position-specific bundle has not been fitted.")
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
        output = frame[context_columns].copy()
        quantile_columns = [
            f"{self.target}_q{int(round(quantile * 100)):02d}"
            for quantile in sorted(self.config.quantiles)
        ]
        for column in quantile_columns:
            output[column] = 0.0
        for position, subset in frame.groupby("position", sort=False):
            bundle = self.models.get(str(position))
            if bundle is None:
                continue
            predicted = bundle.predict(subset)
            for column in quantile_columns:
                output.loc[subset.index, column] = predicted[column].to_numpy()
        return output.reset_index(drop=True)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> PositionSpecificQuantileBundle:
        loaded = joblib.load(path)
        if not isinstance(loaded, cls):
            raise TypeError(f"Expected {cls.__name__}, received {type(loaded).__name__}.")
        return loaded
