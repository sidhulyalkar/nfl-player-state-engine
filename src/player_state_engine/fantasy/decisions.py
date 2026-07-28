from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from player_state_engine.fantasy.league import LeagueConfig


@dataclass(slots=True)
class TradeEvaluation:
    median_delta: float
    floor_delta: float
    ceiling_delta: float
    roster_fit_delta: float
    recommendation_score: float


def _slots(config: LeagueConfig) -> list[tuple[str, set[str]]]:
    slots: list[tuple[str, set[str]]] = []
    for position in ("QB", "RB", "WR", "TE"):
        for number in range(config.roster_slots.get(position, 0)):
            slots.append((f"{position}{number + 1}", {position}))
    for number in range(config.roster_slots.get("FLEX", 0)):
        slots.append((f"FLEX{number + 1}", {"RB", "WR", "TE"}))
    for number in range(config.roster_slots.get("SUPERFLEX", 0)):
        slots.append((f"SUPERFLEX{number + 1}", {"QB", "RB", "WR", "TE"}))
    return slots


def optimize_lineup(
    players: pd.DataFrame, config: LeagueConfig, score_column: str = "lineup_score"
) -> pd.DataFrame:
    """Find the maximum-score legal lineup with assignment optimization."""
    if players.empty:
        return players.copy()
    slots = _slots(config)
    if not slots:
        raise ValueError("League has no starting roster slots.")
    data = players.reset_index(drop=True).copy()
    scores = pd.to_numeric(data[score_column], errors="coerce").fillna(-1e6).to_numpy()
    matrix = np.full((len(data), len(slots)), -1e6, dtype=float)
    for i, position in enumerate(data["position"].astype(str)):
        for j, (_, eligible) in enumerate(slots):
            if position in eligible:
                matrix[i, j] = scores[i]
    row, col = linear_sum_assignment(-matrix)
    selected = []
    for player_index, slot_index in zip(row, col, strict=True):
        if matrix[player_index, slot_index] <= -1e5:
            continue
        record = data.iloc[player_index].to_dict()
        record["assigned_slot"] = slots[slot_index][0]
        selected.append(record)
    return pd.DataFrame(selected).sort_values("assigned_slot").reset_index(drop=True)


def _numeric(frame: pd.DataFrame, name: str, default: float) -> pd.Series:
    source = frame[name] if name in frame else pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(source, errors="coerce").fillna(default)


def rank_waiver_candidates(
    candidates: pd.DataFrame,
    roster: pd.DataFrame,
    *,
    faab_budget: float = 100.0,
) -> pd.DataFrame:
    """Rank waiver candidates by roster-relative upgrade and role-change evidence.

    ``faab_recommendation`` is a bounded planning amount, not a claim that every
    league should bid the same percentage. It should be interpreted alongside
    league size, transaction rules, roster need, and manager behavior.
    """
    data = candidates.copy()
    rostered = roster.copy()
    if "decision_value" not in data:
        raise ValueError("Waiver candidates require decision_value.")
    replacement = (
        rostered.groupby("position")["decision_value"].min().to_dict()
        if not rostered.empty and "decision_value" in rostered
        else {}
    )
    data["roster_replacement_value"] = data["position"].map(replacement).fillna(0.0)
    data["waiver_upgrade"] = data["decision_value"] - data["roster_replacement_value"]
    role_growth = _numeric(data, "role_growth_score", 0.0)
    opportunity = _numeric(data, "opportunity_confidence", 0.5).clip(0, 1)
    availability = _numeric(data, "availability_probability", 1.0).clip(0, 1)
    breakout = _numeric(data, "breakout_probability", 0.0).clip(0, 1)
    data["faab_score"] = (
        0.50 * data["waiver_upgrade"].rank(pct=True)
        + 0.18 * role_growth.rank(pct=True)
        + 0.14 * opportunity.rank(pct=True)
        + 0.08 * availability.rank(pct=True)
        + 0.10 * breakout.rank(pct=True)
    ) * 100
    budget = max(float(faab_budget), 0.0)
    # Aggressive at the very top, but never recommends an all-in bid from model
    # rank alone. Users can override based on league context and desperation.
    data["faab_recommendation"] = budget * np.clip(
        (data["faab_score"] / 100.0) ** 2 * 0.55, 0, 0.55
    )
    return data.sort_values(["waiver_upgrade", "faab_score"], ascending=False).reset_index(
        drop=True
    )


def evaluate_trade(
    incoming: pd.DataFrame,
    outgoing: pd.DataFrame,
    roster_fit_delta: float = 0.0,
    risk_preference: float = 0.5,
) -> TradeEvaluation:
    def total(frame: pd.DataFrame, column: str) -> float:
        return float(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())

    floor = total(incoming, "floor_vorp") - total(outgoing, "floor_vorp")
    median = total(incoming, "vorp") - total(outgoing, "vorp")
    ceiling = total(incoming, "upside_vorp") - total(outgoing, "upside_vorp")
    r = float(np.clip(risk_preference, 0, 1))
    score = (1 - r) * floor + 0.5 * median + r * ceiling + roster_fit_delta
    return TradeEvaluation(median, floor, ceiling, roster_fit_delta, score)
