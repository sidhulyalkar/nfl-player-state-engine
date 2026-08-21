from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(slots=True)
class _CalibrationCell:
    lower_adjustment: float
    upper_adjustment: float
    effective_n: float
    rows: int


@dataclass(slots=True)
class RecencyWeightedConditionalConformal:
    """Conditional q10/q90 conformal adjustment with hierarchical fallback.

    Calibration rows must be historical relative to the forecast rows. Cells are learned for
    position × target and shrink to target then global when support is sparse. Recent errors get
    more weight without allowing future observations into the calibration set.
    """

    half_life_weeks: float = 10.0
    min_cell_rows: int = 40
    target_coverage: float = 0.80
    cells: dict[tuple[str, str], _CalibrationCell] = field(default_factory=dict)
    target_cells: dict[str, _CalibrationCell] = field(default_factory=dict)
    global_cell: _CalibrationCell | None = None
    fitted_cutoff: tuple[int, int] | None = None

    def _weights(self, season: pd.Series, week: pd.Series) -> np.ndarray:
        ordinal = pd.to_numeric(season, errors="coerce") * 25 + pd.to_numeric(week, errors="coerce")
        latest = float(ordinal.max())
        age = np.maximum(latest - ordinal.to_numpy(dtype=float), 0.0)
        half_life = max(float(self.half_life_weeks), 0.5)
        return np.power(0.5, age / half_life)

    @staticmethod
    def _weighted_quantile(values: np.ndarray, weights: np.ndarray, probability: float) -> float:
        mask = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
        values = values[mask]
        weights = weights[mask]
        if len(values) == 0:
            return 0.0
        order = np.argsort(values, kind="mergesort")
        values = values[order]
        weights = weights[order]
        cumulative = np.cumsum(weights)
        cutoff = float(probability) * float(cumulative[-1])
        index = int(np.searchsorted(cumulative, cutoff, side="left"))
        return float(values[min(index, len(values) - 1)])

    def _fit_cell(self, frame: pd.DataFrame, weights: np.ndarray) -> _CalibrationCell:
        actual = pd.to_numeric(frame["actual"], errors="coerce").to_numpy(dtype=float)
        q10 = pd.to_numeric(frame["q10"], errors="coerce").to_numpy(dtype=float)
        q90 = pd.to_numeric(frame["q90"], errors="coerce").to_numpy(dtype=float)
        lower_nonconformity = np.maximum(q10 - actual, 0.0)
        upper_nonconformity = np.maximum(actual - q90, 0.0)
        tail = max((1.0 - float(self.target_coverage)) / 2.0, 0.001)
        probability = 1.0 - tail
        return _CalibrationCell(
            lower_adjustment=self._weighted_quantile(lower_nonconformity, weights, probability),
            upper_adjustment=self._weighted_quantile(upper_nonconformity, weights, probability),
            effective_n=float(np.sum(weights)),
            rows=int(len(frame)),
        )

    def fit(self, calibration: pd.DataFrame) -> RecencyWeightedConditionalConformal:
        required = {"season", "week", "position", "target", "actual", "q10", "q90"}
        missing = required - set(calibration)
        if missing:
            raise ValueError(f"Calibration frame missing columns: {sorted(missing)}")
        frame = calibration.copy()
        frame = frame.dropna(subset=list(required))
        if len(frame) < max(20, self.min_cell_rows // 2):
            raise ValueError("Insufficient calibration rows")
        weights = self._weights(frame["season"], frame["week"])
        frame["_weight"] = weights
        latest = frame[["season", "week"]].astype(int).sort_values(["season", "week"]).iloc[-1]
        self.fitted_cutoff = (int(latest["season"]), int(latest["week"]))
        self.global_cell = self._fit_cell(frame, frame["_weight"].to_numpy(dtype=float))
        self.target_cells = {}
        self.cells = {}

        for target, group in frame.groupby(frame["target"].astype(str), sort=False):
            self.target_cells[str(target)] = self._fit_cell(
                group, group["_weight"].to_numpy(dtype=float)
            )
        for (position, target), group in frame.groupby(
            [frame["position"].astype(str).str.upper(), frame["target"].astype(str)],
            sort=False,
        ):
            if len(group) < self.min_cell_rows:
                continue
            self.cells[(str(position), str(target))] = self._fit_cell(
                group, group["_weight"].to_numpy(dtype=float)
            )
        return self

    def _cell(self, position: str, target: str) -> tuple[_CalibrationCell, str]:
        key = (str(position).upper(), str(target))
        if key in self.cells:
            return self.cells[key], "position_target"
        if str(target) in self.target_cells:
            return self.target_cells[str(target)], "target"
        if self.global_cell is None:
            raise RuntimeError("Calibrator must be fitted before transform")
        return self.global_cell, "global"

    def transform(self, forecasts: pd.DataFrame) -> pd.DataFrame:
        required = {"position", "target", "q10", "q50", "q90"}
        missing = required - set(forecasts)
        if missing:
            raise ValueError(f"Forecast frame missing columns: {sorted(missing)}")
        out = forecasts.copy()
        lower: list[float] = []
        upper: list[float] = []
        levels: list[str] = []
        effective_n: list[float] = []
        for _, row in out.iterrows():
            cell, level = self._cell(str(row["position"]), str(row["target"]))
            q10 = float(row["q10"]) - cell.lower_adjustment
            q50 = float(row["q50"])
            q90 = float(row["q90"]) + cell.upper_adjustment
            lower.append(min(q10, q50))
            upper.append(max(q90, q50))
            levels.append(level)
            effective_n.append(cell.effective_n)
        out["q10_calibrated"] = lower
        out["q50_calibrated"] = pd.to_numeric(out["q50"], errors="coerce")
        out["q90_calibrated"] = upper
        out["calibration_level"] = levels
        out["calibration_effective_n"] = effective_n
        out["calibration_source"] = "recency_weighted_conditional_conformal_v1"
        return out

    @staticmethod
    def score_coverage(
        frame: pd.DataFrame,
        *,
        actual_column: str = "actual",
        lower_column: str = "q10_calibrated",
        upper_column: str = "q90_calibrated",
    ) -> dict[str, float]:
        actual = pd.to_numeric(frame[actual_column], errors="coerce")
        lower = pd.to_numeric(frame[lower_column], errors="coerce")
        upper = pd.to_numeric(frame[upper_column], errors="coerce")
        valid = actual.notna() & lower.notna() & upper.notna()
        if not valid.any():
            raise ValueError("No valid rows for coverage scoring")
        coverage = ((actual[valid] >= lower[valid]) & (actual[valid] <= upper[valid])).mean()
        sharpness = (upper[valid] - lower[valid]).mean()
        return {"coverage": float(coverage), "mean_interval_width": float(sharpness)}
