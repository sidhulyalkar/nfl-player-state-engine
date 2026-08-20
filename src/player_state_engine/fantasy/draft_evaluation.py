from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class SurvivalEvaluation:
    model: str
    rows: int
    brier_score: float
    log_loss: float
    calibration_error: float
    calibration_slope: float
    calibration_intercept: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PairedSurvivalComparison:
    challenger: str
    baseline: str
    rows: int
    brier_delta: float
    bootstrap_low: float
    bootstrap_high: float
    probability_better: float

    @property
    def supports_promotion(self) -> bool:
        return self.bootstrap_high < 0.0

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["supports_promotion"] = self.supports_promotion
        return payload


def _clean_probability_frame(
    frame: pd.DataFrame,
    *,
    outcome_column: str,
    prediction_column: str,
) -> pd.DataFrame:
    required = {outcome_column, prediction_column}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"draft survival evaluation missing columns: {sorted(missing)}")
    clean = frame.copy()
    clean["_outcome"] = pd.to_numeric(clean[outcome_column], errors="coerce")
    clean["_prediction"] = pd.to_numeric(clean[prediction_column], errors="coerce")
    clean = clean.replace([np.inf, -np.inf], np.nan).dropna(subset=["_outcome", "_prediction"])
    clean = clean.loc[clean["_outcome"].between(0, 1)].copy()
    clean["_prediction"] = clean["_prediction"].clip(1e-6, 1.0 - 1e-6)
    return clean


def _calibration_error(outcome: np.ndarray, prediction: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, max(2, int(bins)) + 1)
    labels = np.clip(np.digitize(prediction, edges[1:-1], right=False), 0, len(edges) - 2)
    error = 0.0
    total = max(len(outcome), 1)
    for label in np.unique(labels):
        mask = labels == label
        if not mask.any():
            continue
        error += float(mask.sum()) / total * abs(float(outcome[mask].mean() - prediction[mask].mean()))
    return float(error)


def _calibration_line(outcome: np.ndarray, prediction: np.ndarray) -> tuple[float, float]:
    if len(outcome) < 2 or float(np.std(prediction)) <= 1e-12:
        return float("nan"), float("nan")
    design = np.column_stack([np.ones(len(prediction)), prediction])
    coefficients, *_ = np.linalg.lstsq(design, outcome, rcond=None)
    return float(coefficients[1]), float(coefficients[0])


def evaluate_survival_predictions(
    frame: pd.DataFrame,
    *,
    model: str,
    prediction_column: str,
    outcome_column: str = "survived_to_next_pick",
    calibration_bins: int = 10,
) -> SurvivalEvaluation:
    """Evaluate survival probability as a probability forecast, not only a ranking."""

    clean = _clean_probability_frame(
        frame,
        outcome_column=outcome_column,
        prediction_column=prediction_column,
    )
    if clean.empty:
        raise ValueError("no finite draft survival rows remain")
    outcome = clean["_outcome"].to_numpy(float)
    prediction = clean["_prediction"].to_numpy(float)
    brier = float(np.mean(np.square(prediction - outcome)))
    log_loss = float(
        -np.mean(outcome * np.log(prediction) + (1.0 - outcome) * np.log(1.0 - prediction))
    )
    slope, intercept = _calibration_line(outcome, prediction)
    return SurvivalEvaluation(
        model=str(model),
        rows=len(clean),
        brier_score=brier,
        log_loss=log_loss,
        calibration_error=_calibration_error(outcome, prediction, bins=calibration_bins),
        calibration_slope=slope,
        calibration_intercept=intercept,
    )


def grouped_survival_report(
    frame: pd.DataFrame,
    *,
    model: str,
    prediction_column: str,
    outcome_column: str = "survived_to_next_pick",
    group_columns: tuple[str, ...] = ("position", "league_type", "draft_round"),
    minimum_rows: int = 30,
) -> pd.DataFrame:
    """Expose where a survival model works instead of hiding heterogeneity in one metric."""

    rows: list[dict[str, object]] = [
        {
            "group": "overall",
            "value": "all",
            **evaluate_survival_predictions(
                frame,
                model=model,
                prediction_column=prediction_column,
                outcome_column=outcome_column,
            ).as_dict(),
        }
    ]
    for group_column in group_columns:
        if group_column not in frame:
            continue
        for value, group in frame.groupby(group_column, dropna=False):
            if len(group) < int(minimum_rows):
                continue
            try:
                evaluation = evaluate_survival_predictions(
                    group,
                    model=model,
                    prediction_column=prediction_column,
                    outcome_column=outcome_column,
                )
            except ValueError:
                continue
            rows.append(
                {
                    "group": str(group_column),
                    "value": str(value),
                    **evaluation.as_dict(),
                }
            )
    return pd.DataFrame(rows)


def compare_survival_models_paired(
    frame: pd.DataFrame,
    *,
    challenger_column: str,
    baseline_column: str,
    challenger_name: str = "challenger",
    baseline_name: str = "baseline",
    outcome_column: str = "survived_to_next_pick",
    block_columns: tuple[str, ...] = ("draft_id",),
    bootstrap_samples: int = 2000,
    seed: int = 42,
) -> PairedSurvivalComparison:
    """Paired block bootstrap of Brier loss difference: challenger minus baseline.

    Negative deltas favor the challenger. Blocks default to whole drafts so observations from
    the same room are never treated as independent evidence.
    """

    required = {outcome_column, challenger_column, baseline_column}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"paired survival comparison missing columns: {sorted(missing)}")
    data = frame.copy()
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.replace([np.inf, -np.inf], np.nan).dropna(subset=list(required)).copy()
    data = data.loc[data[outcome_column].between(0, 1)]
    if data.empty:
        raise ValueError("no finite paired survival rows remain")

    outcome = data[outcome_column].to_numpy(float)
    challenger = data[challenger_column].clip(0, 1).to_numpy(float)
    baseline = data[baseline_column].clip(0, 1).to_numpy(float)
    row_delta = np.square(challenger - outcome) - np.square(baseline - outcome)
    observed = float(np.mean(row_delta))

    usable_blocks = tuple(column for column in block_columns if column in data)
    if usable_blocks:
        if len(usable_blocks) == 1:
            grouped = list(data.assign(_delta=row_delta).groupby(usable_blocks[0], dropna=False))
        else:
            grouped = list(
                data.assign(_delta=row_delta).groupby(list(usable_blocks), dropna=False)
            )
        block_means = np.asarray(
            [float(pd.to_numeric(group["_delta"], errors="coerce").mean()) for _, group in grouped],
            dtype=float,
        )
    else:
        block_means = row_delta.astype(float)
    block_means = block_means[np.isfinite(block_means)]
    if not len(block_means):
        raise ValueError("no finite bootstrap blocks remain")

    rng = np.random.default_rng(int(seed))
    samples = np.empty(max(100, int(bootstrap_samples)), dtype=float)
    for index in range(len(samples)):
        resampled = rng.choice(block_means, size=len(block_means), replace=True)
        samples[index] = float(np.mean(resampled))
    low, high = np.quantile(samples, [0.025, 0.975])
    probability_better = float(np.mean(samples < 0.0))
    return PairedSurvivalComparison(
        challenger=str(challenger_name),
        baseline=str(baseline_name),
        rows=len(data),
        brier_delta=observed,
        bootstrap_low=float(low),
        bootstrap_high=float(high),
        probability_better=probability_better,
    )
