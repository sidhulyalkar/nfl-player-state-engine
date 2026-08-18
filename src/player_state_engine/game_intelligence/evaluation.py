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
    result = {
        "rows": float(len(y)),
        "log_loss": float(log_loss(y, np.column_stack([1.0 - p, p]), labels=[0, 1])),
        "brier": float(np.mean((p - y) ** 2)),
        "mean_predicted_pass_rate": float(p.mean()),
        "observed_pass_rate": float(y.mean()),
        "calibration_error": float(abs(p.mean() - y.mean())),
    }
    result["auc"] = float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan")
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
        .agg(plays=("plays", "median"), pass_rate=("pass_rate", "median"), points=("points", "median"))
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


def evaluate_player_opportunity(
    predicted: pd.DataFrame,
    observed: pd.DataFrame,
) -> dict[str, float]:
    """Evaluate carry/target opportunity without hiding role misses or diluting with zero roles."""
    required = {"game_id", "player_id", "carries", "targets"}
    if required - set(predicted):
        raise ValueError(f"Predicted player opportunity missing: {sorted(required - set(predicted))}")
    if required - set(observed):
        raise ValueError(f"Observed player opportunity missing: {sorted(required - set(observed))}")
    predicted_rows = predicted[["game_id", "player_id", "carries", "targets"]].copy()
    observed_rows = observed[["game_id", "player_id", "carries", "targets"]].copy()
    predicted_rows["player_id"] = predicted_rows["player_id"].astype(str)
    observed_rows["player_id"] = observed_rows["player_id"].astype(str)
    for frame in (predicted_rows, observed_rows):
        for column in ("carries", "targets"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    predicted_rows = predicted_rows.loc[
        predicted_rows[["carries", "targets"]].abs().sum(axis=1).gt(1e-12)
    ].copy()
    observed_rows = observed_rows.loc[
        observed_rows[["carries", "targets"]].abs().sum(axis=1).gt(1e-12)
    ].copy()
    joined = observed_rows.merge(
        predicted_rows,
        on=["game_id", "player_id"],
        suffixes=("_actual", "_pred"),
        how="outer",
        indicator=True,
    )
    if joined.empty:
        raise ValueError("No player opportunity rows")
    for column in ("carries_actual", "targets_actual", "carries_pred", "targets_pred"):
        joined[column] = pd.to_numeric(joined[column], errors="coerce").fillna(0.0)
    carry_error = np.abs(joined["carries_actual"] - joined["carries_pred"])
    target_error = np.abs(joined["targets_actual"] - joined["targets_pred"])
    observed_count = float(len(observed_rows))
    covered_observed = float(joined["_merge"].eq("both").sum())
    return {
        "player_rows": float(len(joined)),
        "predicted_player_rows": float(len(predicted_rows)),
        "observed_player_rows": observed_count,
        "observed_player_coverage": covered_observed / max(observed_count, 1.0),
        "player_carries_mae": float(carry_error.mean()),
        "player_targets_mae": float(target_error.mean()),
        "player_opportunity_mae": float((carry_error + target_error).mean() / 2.0),
    }


def interval_coverage(
    actual: pd.Series | np.ndarray,
    q10: pd.Series | np.ndarray,
    q90: pd.Series | np.ndarray,
) -> float:
    y = np.asarray(actual, dtype=float)
    low = np.asarray(q10, dtype=float)
    high = np.asarray(q90, dtype=float)
    valid = np.isfinite(y) & np.isfinite(low) & np.isfinite(high)
    if not valid.any():
        return float("nan")
    return float(((y[valid] >= low[valid]) & (y[valid] <= high[valid])).mean())


def game_simulation_promotion_gate(
    candidate: dict[str, float],
    baseline: dict[str, float],
    *,
    min_games: int = 100,
    min_play_call_log_loss_improvement: float = 0.001,
    max_team_metric_ratio: float = 1.00,
    max_player_metric_ratio: float = 1.00,
    minimum_interval_coverage: float = 0.75,
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

    required_team = ("team_plays_mae", "team_pass_rate_mae", "team_points_mae")
    for metric in required_team:
        if metric not in candidate or metric not in baseline:
            reasons.append(f"missing required team replay metric: {metric}")
        elif candidate[metric] > baseline[metric] * max_team_metric_ratio:
            reasons.append(f"{metric} regressed versus baseline")

    required_player = ("player_opportunity_mae", "fantasy_pinball_loss")
    for metric in required_player:
        if metric not in candidate or metric not in baseline:
            reasons.append(f"missing required player replay metric: {metric}")
        elif candidate[metric] > baseline[metric] * max_player_metric_ratio:
            reasons.append(f"{metric} regressed versus baseline")

    coverage = candidate.get("fantasy_q10_q90_coverage")
    if coverage is None:
        reasons.append("missing fantasy interval coverage")
    elif coverage < minimum_interval_coverage:
        reasons.append(
            f"fantasy interval coverage below floor: {coverage:.3f} < {minimum_interval_coverage:.3f}"
        )

    metrics = {
        key: float(value)
        for key, value in candidate.items()
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value)
    }
    return SimulationPromotionDecision(promoted=not reasons, reasons=reasons, metrics=metrics)
