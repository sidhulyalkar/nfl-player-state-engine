from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, mean_absolute_error, roc_auc_score

from player_state_engine.game_intelligence.schema import SimulationPromotionDecision


def evaluate_play_call_probabilities(
    labels: pd.Series | np.ndarray,
    pass_probability: pd.Series | np.ndarray,
) -> dict[str, float]:
    y = np.asarray(labels, dtype=float)
    p = np.clip(np.asarray(pass_probability, dtype=float), 1e-6, 1 - 1e-6)
    valid = np.isfinite(y) & np.isfinite(p) & np.isin(y, [0.0, 1.0])
    if valid.sum() == 0:
        raise ValueError("No valid play-call probability rows")
    y = y[valid].astype(int)
    p = p[valid]
    brier = float(np.mean((p - y) ** 2))
    result = {
        "rows": float(len(y)),
        "log_loss": float(log_loss(y, np.column_stack([1.0 - p, p]), labels=[0, 1])),
        "brier": brier,
        "mean_predicted_pass_rate": float(p.mean()),
        "observed_pass_rate": float(y.mean()),
        "calibration_error": float(abs(p.mean() - y.mean())),
    }
    if len(np.unique(y)) > 1:
        result["auc"] = float(roc_auc_score(y, p))
    else:
        result["auc"] = float("nan")
    return result


def evaluate_team_simulation_draws(
    team_draws: pd.DataFrame,
    observed: pd.DataFrame,
) -> dict[str, float]:
    """Evaluate simulated team play volume/pass rate/points against realized games."""
    required_draws = {"game_id", "simulation", "team", "plays", "pass_rate", "points"}
    required_observed = {"game_id", "team", "plays", "pass_rate", "points"}
    if required_draws - set(team_draws):
        raise ValueError(f"Team draws missing: {sorted(required_draws - set(team_draws))}")
    if required_observed - set(observed):
        raise ValueError(f"Observed teams missing: {sorted(required_observed - set(observed))}")
    medians = (
        team_draws.groupby(["game_id", "team"], dropna=False)
        .agg(
            plays=("plays", "median"),
            pass_rate=("pass_rate", "median"),
            points=("points", "median"),
        )
        .reset_index()
    )
    joined = observed.merge(medians, on=["game_id", "team"], suffixes=("_actual", "_pred"))
    if joined.empty:
        raise ValueError("No overlapping simulated and observed team rows")
    return {
        "games": float(joined["game_id"].nunique()),
        "team_plays_mae": float(mean_absolute_error(joined["plays_actual"], joined["plays_pred"])),
        "team_pass_rate_mae": float(
            mean_absolute_error(joined["pass_rate_actual"], joined["pass_rate_pred"])
        ),
        "team_points_mae": float(mean_absolute_error(joined["points_actual"], joined["points_pred"])),
    }


def game_simulation_promotion_gate(
    candidate: dict[str, float],
    baseline: dict[str, float],
    *,
    min_games: int = 100,
    min_play_call_log_loss_improvement: float = 0.001,
    max_team_metric_ratio: float = 1.00,
    max_player_metric_ratio: float = 1.00,
) -> SimulationPromotionDecision:
    """Require broad replay wins before game simulation can alter production projections."""
    reasons: list[str] = []
    games = int(candidate.get("games", 0))
    if games < int(min_games):
        reasons.append(f"insufficient historical games: {games} < {min_games}")

    candidate_log_loss = candidate.get("play_call_log_loss")
    baseline_log_loss = baseline.get("play_call_log_loss")
    if candidate_log_loss is None or baseline_log_loss is None:
        reasons.append("missing play-call log-loss comparison")
    elif candidate_log_loss > baseline_log_loss - min_play_call_log_loss_improvement:
        reasons.append("play-call log loss did not clear baseline improvement threshold")

    for metric in ("team_plays_mae", "team_pass_rate_mae", "team_points_mae"):
        if metric in candidate and metric in baseline:
            if candidate[metric] > baseline[metric] * max_team_metric_ratio:
                reasons.append(f"{metric} regressed versus baseline")

    for metric in ("player_opportunity_mae", "fantasy_pinball_loss"):
        if metric in candidate and metric in baseline:
            if candidate[metric] > baseline[metric] * max_player_metric_ratio:
                reasons.append(f"{metric} regressed versus baseline")

    metrics = {
        key: float(value)
        for key, value in candidate.items()
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value)
    }
    return SimulationPromotionDecision(promoted=not reasons, reasons=reasons, metrics=metrics)
