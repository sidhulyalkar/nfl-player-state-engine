from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

from player_state_engine.config import ModelConfig
from player_state_engine.evaluation.metrics import evaluate_quantiles
from player_state_engine.models.quantile import QuantileModelBundle


@dataclass(slots=True)
class BacktestResult:
    predictions: pd.DataFrame
    metrics: pd.DataFrame


def walk_forward_backtest(
    frame: pd.DataFrame,
    features: Iterable[str],
    target: str,
    config: ModelConfig | None = None,
    min_train_weeks: int = 24,
    retrain_every_weeks: int = 4,
) -> BacktestResult:
    config = config or ModelConfig(targets=(target,))
    features = list(features)
    actual_mask = (
        ~frame["is_projection_row"].astype(bool)
        if "is_projection_row" in frame
        else pd.Series(True, index=frame.index)
    )
    data = frame.loc[actual_mask].copy()
    data["fold_week"] = data["season"] * 25 + data["week"]
    weeks = sorted(data["fold_week"].unique())
    if len(weeks) <= min_train_weeks:
        raise ValueError("Not enough unique weeks for the requested backtest.")

    prediction_parts: list[pd.DataFrame] = []
    metric_rows: list[dict[str, float | int]] = []
    model: QuantileModelBundle | None = None

    for fold_index, test_week in enumerate(weeks[min_train_weeks:]):
        if model is None or fold_index % retrain_every_weeks == 0:
            train = data.loc[data["fold_week"] < test_week]
            model = QuantileModelBundle(config=config).fit(train, features, targets=(target,))
        test = data.loc[data["fold_week"] == test_week].copy()
        predicted = model.predict(test)
        predicted["actual"] = test[target].to_numpy()
        predicted["fold_week"] = test_week
        prediction_parts.append(predicted)
        metrics = evaluate_quantiles(test[target], predicted, target, config.quantiles)
        metric_rows.append({"fold_week": int(test_week), "rows": len(test), **metrics})

    return BacktestResult(
        predictions=pd.concat(prediction_parts, ignore_index=True),
        metrics=pd.DataFrame(metric_rows),
    )
