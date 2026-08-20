from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig


@dataclass(frozen=True, slots=True)
class DraftRoomSimulationConfig:
    """Configuration for the research-only live draft-room simulator."""

    simulations: int = 600
    seed: int = 20260820
    position_need_strength: float = 0.35

    def __post_init__(self) -> None:
        if self.simulations <= 0:
            raise ValueError("simulations must be positive")
        if self.position_need_strength < 0:
            raise ValueError("position_need_strength must be nonnegative")


def _position_demand(config: LeagueConfig) -> dict[str, float]:
    """Approximate room-level positional demand implied by the league roster contract."""

    demand = {position: float(count) for position, count in config.direct_starter_slots.items()}
    for slot, count in config.flex_slots.items():
        eligible = tuple(config.flex_eligibility.get(slot, ()))
        if not eligible or count <= 0:
            continue
        base = np.asarray([max(demand.get(position, 0.5), 0.5) for position in eligible], dtype=float)
        weights = base / max(float(base.sum()), 1e-12)
        for position, weight in zip(eligible, weights, strict=True):
            demand[position] = demand.get(position, 0.0) + float(count) * float(weight)

    bench = float(config.roster_slots.get("BENCH", 0)) * float(config.bench_value_weight)
    if bench > 0 and demand:
        total = sum(max(value, 0.0) for value in demand.values())
        if total > 0:
            for position in tuple(demand):
                demand[position] += bench * max(demand[position], 0.0) / total

    return {position: value * float(config.teams) for position, value in demand.items() if value > 0}


def _fallback_market_adp(board: pd.DataFrame, current_pick: int) -> pd.Series:
    if "decision_specific_score" in board:
        score = pd.to_numeric(board["decision_specific_score"], errors="coerce")
    elif "vorp" in board:
        score = pd.to_numeric(board["vorp"], errors="coerce")
    else:
        score = pd.Series(np.arange(len(board), 0, -1, dtype=float), index=board.index)
    rank = score.rank(method="average", ascending=False, na_option="bottom")
    return rank + max(0, int(current_pick) - 1)


def simulate_draft_room(
    board: pd.DataFrame,
    league: LeagueConfig,
    *,
    current_pick: int,
    next_pick: int | None,
    drafted_position_counts: Mapping[str, int] | None = None,
    simulation: DraftRoomSimulationConfig | None = None,
) -> pd.DataFrame:
    """Simulate correlated opponent selections until the manager's next pick.

    The existing analytic ADP survival estimate treats players independently. Real draft rooms
    cannot do that: one selection removes a player, positional runs alter scarcity, and league
    roster structure changes aggregate demand. This simulator preserves those dependencies while
    remaining deliberately transparent and research-only.

    It returns per-player survival plus the expected best same-position value available at the
    next turn. Missing ADP is imputed from the league-specific decision board and explicitly
    exposed so downstream confidence gates can discount it.
    """

    required = {"player_id", "position"}
    missing = required - set(board.columns)
    if missing:
        raise ValueError(f"draft-room board missing columns: {sorted(missing)}")
    if board["player_id"].astype(str).duplicated().any():
        raise ValueError("draft-room board must contain unique player_id values")

    out = board[["player_id", "position"]].copy()
    if board.empty:
        out["room_survival_to_next_pick"] = pd.Series(dtype=float)
        out["room_survival_standard_error"] = pd.Series(dtype=float)
        out["room_position_wait_value"] = pd.Series(dtype=float)
        out["room_position_wait_loss"] = pd.Series(dtype=float)
        out["room_expected_position_supply_next_pick"] = pd.Series(dtype=float)
        out["room_market_imputed"] = pd.Series(dtype=bool)
        out["room_simulations"] = pd.Series(dtype=int)
        return out

    cfg = simulation or DraftRoomSimulationConfig()
    current_pick = max(1, int(current_pick))
    if next_pick is None or int(next_pick) <= current_pick:
        out["room_survival_to_next_pick"] = 0.0
        out["room_survival_standard_error"] = 0.0
        out["room_position_wait_value"] = 0.0
        out["room_position_wait_loss"] = pd.to_numeric(
            board.get("vorp", pd.Series(0.0, index=board.index)), errors="coerce"
        ).fillna(0.0).clip(lower=0.0).to_numpy(float)
        out["room_expected_position_supply_next_pick"] = 0.0
        out["room_market_imputed"] = True
        out["room_simulations"] = cfg.simulations
        return out

    picks_between = max(0, int(next_pick) - current_pick - 1)
    n_players = len(board)
    positions = board["position"].astype(str).str.upper().to_numpy()

    fallback_adp = _fallback_market_adp(board, current_pick)
    if "market_adp" in board:
        raw_adp = pd.to_numeric(board["market_adp"], errors="coerce")
    elif "market_cost" in board:
        raw_adp = pd.to_numeric(board["market_cost"], errors="coerce")
    else:
        raw_adp = pd.Series(np.nan, index=board.index, dtype=float)
    imputed = raw_adp.isna()
    adp = raw_adp.fillna(fallback_adp).to_numpy(float)

    if "market_adp_sd" in board:
        adp_sd = pd.to_numeric(board["market_adp_sd"], errors="coerce")
    else:
        adp_sd = pd.Series(np.nan, index=board.index, dtype=float)
    default_sd = np.clip(5.0 + 0.055 * np.maximum(adp, 1.0), 6.0, 18.0)
    adp_sd_values = adp_sd.fillna(pd.Series(default_sd, index=board.index)).clip(lower=1.0).to_numpy(float)

    vorp = pd.to_numeric(
        board.get("vorp", pd.Series(0.0, index=board.index)), errors="coerce"
    ).fillna(0.0).clip(lower=0.0).to_numpy(float)

    demand_target = _position_demand(league)
    already = {str(key).upper(): int(value) for key, value in (drafted_position_counts or {}).items()}
    initial_remaining = {
        position: max(float(target) - float(already.get(position, 0)), 0.0)
        for position, target in demand_target.items()
    }

    rng = np.random.default_rng(int(cfg.seed))
    survivors = np.ones((cfg.simulations, n_players), dtype=bool)

    for simulation_index in range(cfg.simulations):
        alive = np.ones(n_players, dtype=bool)
        latent_pick = rng.normal(adp, adp_sd_values)
        remaining = dict(initial_remaining)

        for _ in range(min(picks_between, n_players)):
            alive_indexes = np.flatnonzero(alive)
            if not len(alive_indexes):
                break
            total_remaining = sum(remaining.values())
            if total_remaining > 1e-12:
                pressure = np.asarray(
                    [remaining.get(positions[index], 0.0) / total_remaining for index in alive_indexes],
                    dtype=float,
                )
            else:
                pressure = np.zeros(len(alive_indexes), dtype=float)
            adjusted = latent_pick[alive_indexes] - (
                float(cfg.position_need_strength) * pressure * adp_sd_values[alive_indexes]
            )
            selected_index = int(alive_indexes[int(np.argmin(adjusted))])
            alive[selected_index] = False
            selected_position = positions[selected_index]
            if selected_position in remaining:
                remaining[selected_position] = max(0.0, remaining[selected_position] - 1.0)

        survivors[simulation_index] = alive

    survival = survivors.mean(axis=0)
    survival_se = np.sqrt(np.clip(survival * (1.0 - survival) / float(cfg.simulations), 0.0, None))

    wait_value = np.zeros(n_players, dtype=float)
    expected_supply = np.zeros(n_players, dtype=float)
    for position in np.unique(positions):
        indexes = np.flatnonzero(positions == position)
        if not len(indexes):
            continue
        alive_matrix = survivors[:, indexes]
        position_values = vorp[indexes]
        sampled_values = np.where(alive_matrix, position_values[np.newaxis, :], -np.inf)
        best = np.max(sampled_values, axis=1)
        best = np.where(np.isfinite(best), best, 0.0)
        mean_best = float(np.mean(best))
        mean_supply = float(np.mean(alive_matrix.sum(axis=1)))
        wait_value[indexes] = mean_best
        expected_supply[indexes] = mean_supply

    out["room_survival_to_next_pick"] = survival
    out["room_survival_standard_error"] = survival_se
    out["room_position_wait_value"] = wait_value
    out["room_position_wait_loss"] = np.maximum(vorp - wait_value, 0.0)
    out["room_expected_position_supply_next_pick"] = expected_supply
    out["room_market_imputed"] = imputed.to_numpy(bool)
    out["room_simulations"] = int(cfg.simulations)
    return out
