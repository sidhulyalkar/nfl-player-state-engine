from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

from player_state_engine.simulation.distributions import split_normal_ppf


@dataclass(slots=True)
class SimulationResult:
    player_summary: pd.DataFrame
    team_summary: pd.DataFrame
    game_summary: pd.DataFrame
    draws: np.ndarray


def _nearest_correlation(matrix: np.ndarray) -> np.ndarray:
    symmetric = (matrix + matrix.T) / 2.0
    values, vectors = np.linalg.eigh(symmetric)
    values = np.clip(values, 1e-6, None)
    psd = vectors @ np.diag(values) @ vectors.T
    scale = np.sqrt(np.diag(psd))
    corr = psd / np.outer(scale, scale)
    np.fill_diagonal(corr, 1.0)
    return corr


def build_correlation_matrix(
    players: pd.DataFrame,
    same_team_correlation: float = 0.12,
    opposing_team_correlation: float = -0.03,
) -> np.ndarray:
    n = len(players)
    matrix = np.eye(n)
    teams = players["recent_team"].astype(str).to_numpy()
    positions = (
        players.get("position", pd.Series("UNK", index=players.index)).astype(str).to_numpy()
    )

    for i in range(n):
        for j in range(i + 1, n):
            if teams[i] == teams[j]:
                rho = same_team_correlation
                pair = {positions[i], positions[j]}
                if pair == {"QB", "WR"} or pair == {"QB", "TE"}:
                    rho += 0.10
                if positions[i] == positions[j] == "RB":
                    rho -= 0.10
            else:
                rho = opposing_team_correlation
            matrix[i, j] = matrix[j, i] = float(np.clip(rho, -0.75, 0.75))
    return _nearest_correlation(matrix)


def simulate_slate(
    predictions: pd.DataFrame,
    target: str = "fantasy_points_ppr",
    draws: int = 10_000,
    same_team_correlation: float = 0.12,
    opposing_team_correlation: float = -0.03,
    seed: int = 42,
) -> SimulationResult:
    required = [f"{target}_q10", f"{target}_q50", f"{target}_q90", "game_id", "recent_team"]
    missing = [column for column in required if column not in predictions.columns]
    if missing:
        raise ValueError(f"Predictions missing simulation columns: {missing}")

    rng = np.random.default_rng(seed)
    all_draws = np.zeros((draws, len(predictions)), dtype=float)

    for _, indexes in predictions.groupby("game_id", sort=False).groups.items():
        idx = np.asarray(list(indexes), dtype=int)
        game_players = predictions.loc[idx]
        correlation = build_correlation_matrix(
            game_players,
            same_team_correlation=same_team_correlation,
            opposing_team_correlation=opposing_team_correlation,
        )
        latent = rng.multivariate_normal(np.zeros(len(idx)), correlation, size=draws)
        uniforms = norm.cdf(latent)
        q10 = game_players[f"{target}_q10"].to_numpy(dtype=float)[None, :]
        q50 = game_players[f"{target}_q50"].to_numpy(dtype=float)[None, :]
        q90 = game_players[f"{target}_q90"].to_numpy(dtype=float)[None, :]
        all_draws[:, idx] = split_normal_ppf(uniforms, q10, q50, q90, nonnegative=True)

    player_summary = predictions[
        [
            c
            for c in (
                "season",
                "week",
                "game_id",
                "player_id",
                "player_name",
                "recent_team",
                "opponent_team",
                "position",
            )
            if c in predictions
        ]
    ].copy()
    player_summary["mean"] = all_draws.mean(axis=0)
    player_summary["p10"] = np.quantile(all_draws, 0.10, axis=0)
    player_summary["median"] = np.quantile(all_draws, 0.50, axis=0)
    player_summary["p90"] = np.quantile(all_draws, 0.90, axis=0)
    player_summary["prob_above_model_median"] = (
        all_draws > predictions[f"{target}_q50"].to_numpy(dtype=float)[None, :]
    ).mean(axis=0)

    team_rows: list[dict[str, object]] = []
    for (game_id, team), indexes in predictions.groupby(
        ["game_id", "recent_team"], sort=False
    ).groups.items():
        totals = all_draws[:, list(indexes)].sum(axis=1)
        team_rows.append(
            {
                "game_id": game_id,
                "recent_team": team,
                "mean": float(totals.mean()),
                "p10": float(np.quantile(totals, 0.10)),
                "median": float(np.quantile(totals, 0.50)),
                "p90": float(np.quantile(totals, 0.90)),
            }
        )
    team_summary = pd.DataFrame(team_rows)

    game_rows: list[dict[str, object]] = []
    for game_id, indexes in predictions.groupby("game_id", sort=False).groups.items():
        totals = all_draws[:, list(indexes)].sum(axis=1)
        game_rows.append(
            {
                "game_id": game_id,
                "mean": float(totals.mean()),
                "p10": float(np.quantile(totals, 0.10)),
                "median": float(np.quantile(totals, 0.50)),
                "p90": float(np.quantile(totals, 0.90)),
            }
        )
    game_summary = pd.DataFrame(game_rows)
    return SimulationResult(player_summary, team_summary, game_summary, all_draws)
