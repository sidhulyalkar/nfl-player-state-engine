from __future__ import annotations

from dataclasses import asdict, dataclass
from collections.abc import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from player_state_engine.fantasy.league import LeagueConfig

_NORMAL_Q10_Z = 1.2815515655446004


@dataclass(slots=True)
class RosterImpact:
    player_id: str
    player_name: str
    position: str
    baseline_q10: float
    baseline_q50: float
    baseline_q90: float
    post_q10: float
    post_q50: float
    post_q90: float
    marginal_floor: float
    marginal_median: float
    marginal_ceiling: float
    simulated_delta_q10: float
    simulated_delta_q50: float
    simulated_delta_q90: float
    expected_lineup_gain: float
    probability_improves: float
    starter_probability: float
    projected_slot: str | None
    displaced_player_id: str | None
    displaced_player_name: str | None
    depth_delta: float
    roster_fit_score: float
    simulations: int
    model_source: str = "quantile_roster_counterfactual_v1"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _quantile_columns(frame: pd.DataFrame) -> tuple[str, str, str]:
    candidates = (
        ("season_points_q10", "season_points_q50", "season_points_q90"),
        ("fantasy_points_ppr_q10", "fantasy_points_ppr_q50", "fantasy_points_ppr_q90"),
        ("q10", "q50", "q90"),
    )
    for columns in candidates:
        if all(column in frame for column in columns):
            return columns
    raise ValueError("Roster simulator requires q10/q50/q90 projection columns.")


def _starter_slots(config: LeagueConfig) -> list[tuple[str, tuple[str, ...]]]:
    slots: list[tuple[str, tuple[str, ...]]] = []
    for position, count in config.direct_starter_slots.items():
        if position in {"K", "DEF", "DST"}:
            continue
        for number in range(count):
            slots.append((f"{position}{number + 1}", (position,)))
    for flex_name, count in config.flex_slots.items():
        eligible = tuple(config.flex_eligibility.get(flex_name, ()))
        for number in range(count):
            slots.append((f"{flex_name}{number + 1}", eligible))
    return slots


def _lineup_assignment(
    frame: pd.DataFrame,
    config: LeagueConfig,
    scores: np.ndarray,
) -> tuple[float, dict[str, str]]:
    slots = _starter_slots(config)
    if not slots or frame.empty:
        return 0.0, {}
    positions = frame["position"].astype(str).str.upper().to_numpy()
    matrix = np.full((len(frame), len(slots)), -1e9, dtype=float)
    for player_index, position in enumerate(positions):
        for slot_index, (_, eligible) in enumerate(slots):
            if position in eligible:
                matrix[player_index, slot_index] = scores[player_index]
    row, col = linear_sum_assignment(-matrix)
    total = 0.0
    assignment: dict[str, str] = {}
    for player_index, slot_index in zip(row, col, strict=True):
        value = matrix[player_index, slot_index]
        if value <= -1e8:
            continue
        total += float(value)
        player_id = str(frame.iloc[player_index]["player_id"])
        assignment[player_id] = slots[slot_index][0]
    return total, assignment


def _numeric(frame: pd.DataFrame, column: str) -> np.ndarray:
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0).to_numpy(dtype=float)


def _deterministic_roster_summary(
    roster: pd.DataFrame,
    config: LeagueConfig,
    columns: tuple[str, str, str],
) -> tuple[tuple[float, float, float], dict[str, str]]:
    q10, q50, q90 = columns
    floor_total, _ = _lineup_assignment(roster, config, _numeric(roster, q10))
    median_total, assignment = _lineup_assignment(roster, config, _numeric(roster, q50))
    ceiling_total, _ = _lineup_assignment(roster, config, _numeric(roster, q90))
    return (floor_total, median_total, ceiling_total), assignment


def _sample_quantiles(
    rng: np.random.Generator,
    q10: np.ndarray,
    q50: np.ndarray,
    q90: np.ndarray,
    simulations: int,
) -> np.ndarray:
    z = rng.standard_normal((simulations, len(q50)))
    low_slope = np.maximum((q50 - q10) / _NORMAL_Q10_Z, 1e-6)
    high_slope = np.maximum((q90 - q50) / _NORMAL_Q10_Z, 1e-6)
    samples = np.where(z < 0, q50 + z * low_slope, q50 + z * high_slope)
    return np.maximum(samples, 0.0)


def _depth_value(roster: pd.DataFrame, assignment: dict[str, str], q50_column: str) -> float:
    if roster.empty:
        return 0.0
    starter_ids = set(assignment)
    bench = roster.loc[~roster["player_id"].astype(str).isin(starter_ids)].copy()
    if bench.empty:
        return 0.0
    values = pd.to_numeric(bench[q50_column], errors="coerce").fillna(0.0)
    return float(values.nlargest(min(4, len(values))).sum() * 0.15)


def _roster_rows(full_board: pd.DataFrame, player_ids: Iterable[str]) -> pd.DataFrame:
    ids = {str(player_id) for player_id in player_ids}
    if not ids:
        return full_board.iloc[0:0].copy()
    return full_board.loc[full_board["player_id"].astype(str).isin(ids)].copy().reset_index(drop=True)


def evaluate_candidate_impacts(
    full_board: pd.DataFrame,
    config: LeagueConfig,
    roster_player_ids: Iterable[str],
    candidate_player_ids: Iterable[str],
    *,
    simulations: int = 600,
    seed: int = 42,
) -> list[RosterImpact]:
    """Estimate marginal roster value by optimizing legal starters in each quantile draw."""
    if full_board.empty:
        return []
    simulations = max(100, min(int(simulations), 5000))
    columns = _quantile_columns(full_board)
    _, q50_col, _ = columns
    roster_ids = tuple(str(value) for value in roster_player_ids)
    baseline = _roster_rows(full_board, roster_ids)
    baseline_summary, baseline_assignment = _deterministic_roster_summary(baseline, config, columns)
    baseline_depth = _depth_value(baseline, baseline_assignment, q50_col)

    requested = [str(player_id) for player_id in candidate_player_ids]
    candidates = full_board.loc[full_board["player_id"].astype(str).isin(requested)].copy()
    if candidates.empty:
        return []

    impacts: list[RosterImpact] = []
    roster_id_set = set(roster_ids)
    for candidate_index, candidate in candidates.iterrows():
        candidate_id = str(candidate["player_id"])
        if candidate_id in roster_id_set:
            continue
        post = pd.concat([baseline, candidate.to_frame().T], ignore_index=True)
        post["position"] = post["position"].astype(str).str.upper()
        post_summary, post_assignment = _deterministic_roster_summary(post, config, columns)
        post_depth = _depth_value(post, post_assignment, q50_col)
        projected_slot = post_assignment.get(candidate_id)

        displaced_ids = set(baseline_assignment) - set(post_assignment)
        displaced_id = next(iter(displaced_ids), None)
        displaced_name = None
        if displaced_id is not None:
            rows = baseline.loc[baseline["player_id"].astype(str).eq(displaced_id)]
            if not rows.empty:
                displaced_name = str(rows.iloc[0].get("player_name") or displaced_id)

        union = post.reset_index(drop=True)
        rng = np.random.default_rng(seed + int(candidate_index) * 7919)
        q10_col, q50_col, q90_col = columns
        samples = _sample_quantiles(
            rng,
            _numeric(union, q10_col),
            _numeric(union, q50_col),
            _numeric(union, q90_col),
            simulations,
        )
        baseline_mask = union["player_id"].astype(str).ne(candidate_id).to_numpy()
        baseline_union = union.loc[baseline_mask].reset_index(drop=True)
        candidate_starts = 0
        deltas = np.zeros(simulations, dtype=float)
        for simulation in range(simulations):
            baseline_total, _ = _lineup_assignment(
                baseline_union, config, samples[simulation, baseline_mask]
            )
            post_total, assignment = _lineup_assignment(union, config, samples[simulation])
            deltas[simulation] = post_total - baseline_total
            candidate_starts += int(candidate_id in assignment)

        delta_q10, delta_q50, delta_q90 = np.quantile(deltas, [0.10, 0.50, 0.90])
        deterministic_floor = post_summary[0] - baseline_summary[0]
        deterministic_median = post_summary[1] - baseline_summary[1]
        deterministic_ceiling = post_summary[2] - baseline_summary[2]
        depth_delta = post_depth - baseline_depth
        probability_improves = float(np.mean(deltas > 1e-9))
        starter_probability = float(candidate_starts / simulations)
        fit_raw = (
            0.50 * max(0.0, deterministic_median)
            + 0.20 * max(0.0, deterministic_floor)
            + 0.15 * max(0.0, deterministic_ceiling)
            + 0.10 * max(0.0, depth_delta)
            + 0.05 * 10.0 * starter_probability
        )
        roster_fit_score = float(100.0 * (1.0 - np.exp(-fit_raw / 25.0)))
        impacts.append(
            RosterImpact(
                player_id=candidate_id,
                player_name=str(candidate.get("player_name") or candidate_id),
                position=str(candidate.get("position") or "UNK"),
                baseline_q10=float(baseline_summary[0]),
                baseline_q50=float(baseline_summary[1]),
                baseline_q90=float(baseline_summary[2]),
                post_q10=float(post_summary[0]),
                post_q50=float(post_summary[1]),
                post_q90=float(post_summary[2]),
                marginal_floor=float(deterministic_floor),
                marginal_median=float(deterministic_median),
                marginal_ceiling=float(deterministic_ceiling),
                simulated_delta_q10=float(delta_q10),
                simulated_delta_q50=float(delta_q50),
                simulated_delta_q90=float(delta_q90),
                expected_lineup_gain=float(np.mean(deltas)),
                probability_improves=probability_improves,
                starter_probability=starter_probability,
                projected_slot=projected_slot,
                displaced_player_id=displaced_id,
                displaced_player_name=displaced_name,
                depth_delta=float(depth_delta),
                roster_fit_score=roster_fit_score,
                simulations=simulations,
            )
        )
    requested_order = {player_id: index for index, player_id in enumerate(requested)}
    impacts.sort(key=lambda item: requested_order.get(item.player_id, len(requested_order)))
    return impacts
