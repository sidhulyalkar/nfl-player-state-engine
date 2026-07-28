from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

import joblib
import pandas as pd

from player_state_engine.config import ModelConfig
from player_state_engine.models.position_quantile import PositionSpecificQuantileBundle
from player_state_engine.models.quantile import QuantileModelBundle

POSITION_SPECIFIC_TARGETS = {"carries"}


class HybridQuantileModelBundle:
    """Target-aware production bundle.

    Most targets use pooled partial-sharing models. Structurally zero-inflated
    targets such as carries use independent position heads so the large number
    of zero-WR rows cannot collapse the QB/RB conditional median.
    """

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or ModelConfig()
        self.features: list[str] = []
        self.targets: list[str] = []
        self.models: dict[str, QuantileModelBundle | PositionSpecificQuantileBundle] = {}
        self.training_summary: dict[str, dict[str, object]] = {}
        self.calibrators: dict[str, object] = {}

    def fit(
        self,
        frame: pd.DataFrame,
        features: Iterable[str],
        targets: Iterable[str] | None = None,
    ) -> HybridQuantileModelBundle:
        self.features = list(features)
        requested = list(targets or self.config.targets)
        self.targets = [target for target in requested if target in frame.columns]
        if not self.features:
            raise ValueError("No feature columns were supplied.")
        if not self.targets:
            raise ValueError("None of the requested targets exist in the training frame.")

        self.models = {}
        self.training_summary = {}
        for target in self.targets:
            if target in POSITION_SPECIFIC_TARGETS:
                model = PositionSpecificQuantileBundle(self.config).fit(
                    frame,
                    self.features,
                    target,
                    min_rows_per_position=max(25, self.config.min_samples_leaf * 2),
                )
                self.training_summary[target] = {
                    "strategy": "position_specific_quantile",
                    "positions": sorted(model.models),
                    "rows": int(len(frame)),
                }
            else:
                model = QuantileModelBundle(self.config).fit(
                    frame, self.features, targets=(target,)
                )
                summary = dict(model.training_summary[target])
                summary["strategy"] = "pooled_quantile"
                self.training_summary[target] = summary
            self.models[target] = model
        return self

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        if not self.models:
            raise RuntimeError("Hybrid bundle has not been fitted.")
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
        output = frame[context_columns].copy().reset_index(drop=True)
        for target in self.targets:
            predicted = self.models[target].predict(frame)
            target_columns = [column for column in predicted if column.startswith(f"{target}_q")]
            for column in target_columns:
                output[column] = predicted[column].to_numpy()
            calibrator = self.calibrators.get(target)
            if calibrator is not None:
                calibrated = calibrator.transform(output, target)
                for column in target_columns:
                    output[column] = calibrated[column].to_numpy()
                output[f"{target}_conformal_applied"] = 1
        return output

    def set_calibrator(self, target: str, calibrator: object) -> None:
        if target not in self.targets:
            raise ValueError(f"Cannot attach calibrator for untrained target {target!r}.")
        self.calibrators[target] = calibrator

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "version": 1,
                "bundle_type": "hybrid_quantile",
                "config": asdict(self.config),
                "features": self.features,
                "targets": self.targets,
                "models": self.models,
                "training_summary": self.training_summary,
                "calibrators": self.calibrators,
            },
            path,
        )
        return path

    @classmethod
    def load(cls, path: str | Path) -> HybridQuantileModelBundle:
        payload = joblib.load(path)
        if payload.get("bundle_type") != "hybrid_quantile":
            raise TypeError("Saved model is not a HybridQuantileModelBundle.")
        bundle = cls(ModelConfig(**payload["config"]))
        bundle.features = list(payload["features"])
        bundle.targets = list(payload["targets"])
        bundle.models = payload["models"]
        bundle.training_summary = payload.get("training_summary", {})
        bundle.calibrators = payload.get("calibrators", {})
        return bundle
