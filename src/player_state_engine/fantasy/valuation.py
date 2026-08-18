from __future__ import annotations

from collections import defaultdict
from math import ceil

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig

CORE_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF", "DST")


def starter_allocation(
    projections: pd.DataFrame,
    config: LeagueConfig,
    value_column: str = "season_points_q50",
) -> dict[str, int]:
    """Estimate how many starters the league consumes at each position.

    Fixed slots are allocated first. Flexible slots are then allocated one seat at a
    time to the eligible position whose next undrafted player has the highest projected
    value. This produces format-sensitive demand without hard-coded 45/45/10 flex shares
    and naturally handles 2QB, superflex, three-flex, shallow and deep leagues.
    """
    if value_column not in projections:
        raise ValueError(f"Missing valuation column: {value_column}")

    values: dict[str, list[float]] = {}
    for position, group in projections.groupby(projections["position"].astype(str).str.upper()):
        ranked = pd.to_numeric(group[value_column], errors="coerce").dropna().sort_values(ascending=False)
        values[str(position)] = ranked.astype(float).tolist()

    allocation: defaultdict[str, int] = defaultdict(int)
    for position, slots in config.direct_starter_slots.items():
        if position in {"DST", "DEF"}:
            position = "DEF" if "DEF" in values else "DST"
        allocation[position] += int(slots) * config.teams

    for slot, slots_per_team in config.flex_slots.items():
        eligible = tuple(config.flex_eligibility.get(slot, ()))
        seats = int(slots_per_team) * config.teams
        for _ in range(seats):
            best_position: str | None = None
            best_value = -np.inf
            for position in eligible:
                position_values = values.get(position, [])
                index = allocation[position]
                candidate = position_values[index] if index < len(position_values) else -np.inf
                if candidate > best_value:
                    best_value = candidate
                    best_position = position
            if best_position is None or not np.isfinite(best_value):
                break
            allocation[best_position] += 1

    return dict(allocation)


def replacement_ranks(
    projections: pd.DataFrame,
    config: LeagueConfig,
    value_column: str = "season_points_q50",
) -> dict[str, int]:
    starter_counts = starter_allocation(projections, config, value_column=value_column)
    positions = {str(position).upper() for position in projections["position"].dropna().unique()}
    ranks: dict[str, int] = {}
    for position in positions:
        starters = starter_counts.get(position, 0)
        if starters <= 0:
            # Positions with no legal starting slot should not get an artificial deep replacement line.
            ranks[position] = 1
            continue
        buffer = ceil(
            config.replacement_buffer
            * config.teams
            * config.replacement_buffer_fraction
        )
        ranks[position] = max(1, starters + buffer)
    return ranks


def calculate_replacement_levels(
    projections: pd.DataFrame, config: LeagueConfig, value_column: str = "season_points_q50"
) -> dict[str, float]:
    levels: dict[str, float] = {}
    ranks = replacement_ranks(projections, config, value_column=value_column)
    normalized_position = projections["position"].astype(str).str.upper()
    for position, rank in ranks.items():
        group = projections.loc[normalized_position.eq(position)].copy()
        if group.empty:
            continue
        group[value_column] = pd.to_numeric(group[value_column], errors="coerce")
        ranked = group.dropna(subset=[value_column]).sort_values(value_column, ascending=False)
        if ranked.empty:
            levels[position] = 0.0
            continue
        clamped_rank = min(max(1, rank), len(ranked))
        levels[position] = float(ranked.iloc[clamped_rank - 1][value_column])
    return levels


def value_players(projections: pd.DataFrame, config: LeagueConfig) -> pd.DataFrame:
    """Produce league-specific value, floor, upside, scarcity and risk scores."""
    data = projections.copy()
    required = {
        "player_id",
        "player_name",
        "position",
        "season_points_q10",
        "season_points_q50",
        "season_points_q90",
    }
    missing = required - set(data)
    if missing:
        raise ValueError(f"Valuation projections missing: {sorted(missing)}")

    data["position"] = data["position"].astype(str).str.upper()
    replacements = calculate_replacement_levels(data, config)
    ranks = replacement_ranks(data, config)
    starter_counts = starter_allocation(data, config)
    data["replacement_points"] = data["position"].map(replacements).fillna(0.0)
    data["replacement_rank"] = data["position"].map(ranks).fillna(1).astype(int)
    data["league_starter_demand"] = data["position"].map(starter_counts).fillna(0).astype(int)
    data["vorp"] = data["season_points_q50"] - data["replacement_points"]
    data["floor_vorp"] = data["season_points_q10"] - data["replacement_points"]
    data["upside_vorp"] = data["season_points_q90"] - data["replacement_points"]
    data["uncertainty"] = data["season_points_q90"] - data["season_points_q10"]
    data["availability_probability"] = (
        pd.to_numeric(
            data["availability_probability"]
            if "availability_probability" in data
            else pd.Series(1.0, index=data.index),
            errors="coerce",
        )
        .fillna(1.0)
        .clip(0, 1)
    )
    data["opportunity_confidence"] = (
        pd.to_numeric(
            data["opportunity_confidence"]
            if "opportunity_confidence" in data
            else pd.Series(0.5, index=data.index),
            errors="coerce",
        )
        .fillna(0.5)
        .clip(0, 1)
    )
    data["role_growth_score"] = pd.to_numeric(
        data["role_growth_score"]
        if "role_growth_score" in data
        else pd.Series(0.0, index=data.index),
        errors="coerce",
    ).fillna(0.0)
    data["schedule_score"] = pd.to_numeric(
        data["schedule_score"] if "schedule_score" in data else pd.Series(0.0, index=data.index),
        errors="coerce",
    ).fillna(0.0)

    risk = float(np.clip(config.risk_preference, 0, 1))
    median_bonus = 0.0
    if config.median_scoring:
        # A second game against the weekly median rewards reliable weekly scoring.
        # Team-level simulation is the gold standard, but floor VORP is a useful draft-time proxy.
        median_bonus = config.median_game_weight * 0.15 * data["floor_vorp"]

    data["decision_value"] = (
        data["availability_probability"]
        * ((1 - risk) * data["floor_vorp"] + 0.5 * data["vorp"] + risk * data["upside_vorp"])
        + 5.0 * data["opportunity_confidence"]
        + 3.0 * data["role_growth_score"]
        + 2.0 * data["schedule_score"]
        + median_bonus
    )

    # Scarcity is now based on distance above the league-specific replacement line rather
    # than a within-position percentile that ignores roster depth.
    positive_vorp = data["vorp"].clip(lower=0.0)
    scale = positive_vorp.groupby(data["position"]).transform("max").replace(0.0, np.nan)
    data["scarcity_score"] = (positive_vorp / scale).fillna(0.0).clip(0, 1)
    data["trade_value"] = 100 * data["decision_value"].rank(pct=True)
    data["draft_value"] = data["decision_value"]
    return data.sort_values("decision_value", ascending=False).reset_index(drop=True)


def weekly_start_sit(projections: pd.DataFrame, risk_preference: float = 0.5) -> pd.DataFrame:
    data = projections.copy()
    floor = data["fantasy_points_ppr_q10"]
    median = data["fantasy_points_ppr_q50"]
    ceiling = data["fantasy_points_ppr_q90"]
    r = float(np.clip(risk_preference, 0, 1))
    data["lineup_score"] = (1 - r) * floor + 0.5 * median + r * ceiling
    data["downside"] = median - floor
    data["upside"] = ceiling - median
    return data.sort_values("lineup_score", ascending=False)
