from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from player_state_engine.state_graph.types import ForecastQuantiles


def _pinball(actual: np.ndarray, prediction: np.ndarray, quantile: float) -> float:
    residual = actual - prediction
    loss = np.maximum(quantile * residual, (quantile - 1.0) * residual)
    return float(np.nanmean(loss))


@dataclass(slots=True, frozen=True)
class FusionKey:
    position: str = "*"
    target: str = "*"
    horizon: str = "*"
    regime_maturity: str = "*"


@dataclass(slots=True)
class HierarchicalForecastFusion:
    """Historically learned expert blending with explicit hierarchical shrinkage."""

    shrinkage_rows: float = 120.0
    min_rows: int = 20
    epsilon: float = 1e-6
    weights: dict[FusionKey, dict[str, float]] = field(default_factory=dict)
    experts: tuple[str, ...] = ()

    def _raw_weights(self, frame: pd.DataFrame) -> dict[str, float]:
        losses: dict[str, float] = {}
        for expert, group in frame.groupby(frame["expert"].astype(str), sort=False):
            actual = pd.to_numeric(group["actual"], errors="coerce").to_numpy(dtype=float)
            q10 = pd.to_numeric(group["q10"], errors="coerce").to_numpy(dtype=float)
            q50 = pd.to_numeric(group["q50"], errors="coerce").to_numpy(dtype=float)
            q90 = pd.to_numeric(group["q90"], errors="coerce").to_numpy(dtype=float)
            loss = (
                _pinball(actual, q10, 0.10)
                + 2.0 * _pinball(actual, q50, 0.50)
                + _pinball(actual, q90, 0.90)
            ) / 4.0
            losses[str(expert)] = max(loss, self.epsilon)
        inverse = {expert: 1.0 / loss for expert, loss in losses.items()}
        total = sum(inverse.values())
        if total <= 0:
            count = max(len(inverse), 1)
            return {expert: 1.0 / count for expert in inverse}
        return {expert: value / total for expert, value in inverse.items()}

    @staticmethod
    def _normalize(weights: dict[str, float], experts: Iterable[str]) -> dict[str, float]:
        completed = {expert: max(0.0, float(weights.get(expert, 0.0))) for expert in experts}
        total = sum(completed.values())
        if total <= 0:
            count = max(len(completed), 1)
            return {expert: 1.0 / count for expert in completed}
        return {expert: value / total for expert, value in completed.items()}

    def _shrink(
        self,
        local: dict[str, float],
        parent: dict[str, float],
        rows: int,
    ) -> dict[str, float]:
        strength = float(rows) / (float(rows) + max(float(self.shrinkage_rows), 1.0))
        blended = {
            expert: strength * local.get(expert, 0.0) + (1.0 - strength) * parent.get(expert, 0.0)
            for expert in self.experts
        }
        return self._normalize(blended, self.experts)

    def fit(self, archive: pd.DataFrame) -> HierarchicalForecastFusion:
        required = {
            "expert",
            "actual",
            "q10",
            "q50",
            "q90",
            "position",
            "target",
            "horizon",
            "regime_maturity",
        }
        missing = required - set(archive)
        if missing:
            raise ValueError(f"Fusion archive missing columns: {sorted(missing)}")
        frame = archive.dropna(subset=list(required)).copy()
        self.experts = tuple(sorted(frame["expert"].astype(str).unique()))
        if len(self.experts) < 2:
            raise ValueError("Fusion requires at least two archived experts")

        global_key = FusionKey()
        global_weights = self._normalize(self._raw_weights(frame), self.experts)
        self.weights = {global_key: global_weights}

        levels = (
            ("position",),
            ("position", "target"),
            ("position", "target", "horizon"),
            ("position", "target", "horizon", "regime_maturity"),
        )
        for columns in levels:
            for values, group in frame.groupby(list(columns), sort=False, dropna=False):
                if not isinstance(values, tuple):
                    values = (values,)
                if len(group) < self.min_rows:
                    continue
                mapping = dict(zip(columns, (str(value) for value in values), strict=True))
                key = FusionKey(
                    position=mapping.get("position", "*").upper(),
                    target=mapping.get("target", "*"),
                    horizon=mapping.get("horizon", "*"),
                    regime_maturity=mapping.get("regime_maturity", "*").upper(),
                )
                parent = FusionKey(
                    position=key.position if len(columns) > 1 else "*",
                    target=key.target if len(columns) > 2 else "*",
                    horizon=key.horizon if len(columns) > 3 else "*",
                    regime_maturity="*",
                )
                parent_weights = self.weights.get(parent, global_weights)
                local = self._normalize(self._raw_weights(group), self.experts)
                self.weights[key] = self._shrink(local, parent_weights, len(group))
        return self

    def weights_for(
        self,
        *,
        position: str,
        target: str,
        horizon: str,
        regime_maturity: str,
    ) -> tuple[dict[str, float], FusionKey]:
        candidates = (
            FusionKey(position.upper(), target, horizon, regime_maturity.upper()),
            FusionKey(position.upper(), target, horizon, "*"),
            FusionKey(position.upper(), target, "*", "*"),
            FusionKey(position.upper(), "*", "*", "*"),
            FusionKey(),
        )
        for key in candidates:
            if key in self.weights:
                return self.weights[key].copy(), key
        raise RuntimeError("Fusion layer must be fitted before use")

    def blend(
        self,
        forecasts: dict[str, ForecastQuantiles],
        *,
        position: str,
        target: str,
        horizon: str,
        regime_maturity: str,
    ) -> tuple[ForecastQuantiles, dict[str, object]]:
        weights, key = self.weights_for(
            position=position,
            target=target,
            horizon=horizon,
            regime_maturity=regime_maturity,
        )
        available = {expert: forecast for expert, forecast in forecasts.items() if expert in weights}
        if not available:
            raise ValueError("No forecast experts overlap fitted fusion experts")
        normalized = self._normalize({expert: weights[expert] for expert in available}, available)
        q10 = sum(normalized[expert] * forecast.q10 for expert, forecast in available.items())
        q50 = sum(normalized[expert] * forecast.q50 for expert, forecast in available.items())
        q90 = sum(normalized[expert] * forecast.q90 for expert, forecast in available.items())
        mean_values = [
            normalized[expert] * forecast.mean
            for expert, forecast in available.items()
            if forecast.mean is not None
        ]
        disagreement = float(np.std([forecast.q50 for forecast in available.values()], ddof=0))
        blended = ForecastQuantiles(
            q10=float(q10),
            q50=float(q50),
            q90=float(q90),
            mean=float(sum(mean_values)) if len(mean_values) == len(available) else None,
            source="hierarchical_forecast_fusion_v1",
        )
        diagnostics = {
            "weights": normalized,
            "hierarchy_key": key,
            "expert_medians": {expert: forecast.q50 for expert, forecast in available.items()},
            "median_disagreement_std": disagreement,
        }
        return blended, diagnostics
