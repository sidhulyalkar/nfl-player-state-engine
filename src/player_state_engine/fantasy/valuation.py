from __future__ import annotations

from collections import defaultdict
from math import ceil

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import prepare_league_scoring_quantiles

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
        ranked = (
            pd.to_numeric(group[value_column], errors="coerce").dropna().sort_values(ascending=False)
        )
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
            config.replacement_buffer * config.teams * config.replacement_buffer_fraction
        )
        ranks[position] = max(1, starters + buffer)
    return ranks


def calculate_replacement_levels(
    projections: pd.DataFrame,
    config: LeagueConfig,
    value_column: str = "season_points_q50",
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


def _percentile(series: pd.Series) -> pd.Series:
    if len(series) <= 1:
        return pd.Series(0.5, index=series.index, dtype=float)
    return series.rank(method="average", pct=True).fillna(0.5)


def _add_position_curve_features(data: pd.DataFrame) -> pd.DataFrame:
    """Describe the actual league-specific value curve instead of a position percentile alone."""
    out = data.copy()
    out["projection_position_rank"] = 0
    out["players_above_replacement"] = 0
    out["replacement_slope"] = 0.0
    out["next_player_vorp_drop"] = 0.0

    for _, group in out.groupby("position", sort=False):
        ordered = group.sort_values("valuation_points_q50", ascending=False)
        ranks = np.arange(1, len(ordered) + 1, dtype=int)
        out.loc[ordered.index, "projection_position_rank"] = ranks
        positive = int((ordered["vorp"] > 0).sum())
        out.loc[ordered.index, "players_above_replacement"] = positive

        replacement_rank = max(1, int(ordered["replacement_rank"].iloc[0]))
        distance = np.maximum(replacement_rank - ranks, 1)
        slope = ordered["vorp"].clip(lower=0.0).to_numpy(float) / distance
        out.loc[ordered.index, "replacement_slope"] = slope

        values = ordered["vorp"].to_numpy(float)
        next_values = np.roll(values, -1)
        if len(values):
            next_values[-1] = values[-1]
        out.loc[ordered.index, "next_player_vorp_drop"] = np.maximum(0.0, values - next_values)

    out["projection_position_rank"] = out["projection_position_rank"].astype(int)
    out["players_above_replacement"] = out["players_above_replacement"].astype(int)
    slope_pct = _percentile(out["replacement_slope"].clip(lower=0.0))
    supply = out["players_above_replacement"].astype(float)
    inverse_supply_pct = 1.0 - _percentile(supply)
    out["dynamic_scarcity_score"] = (0.70 * slope_pct + 0.30 * inverse_supply_pct).clip(0, 1)
    return out


def value_players(projections: pd.DataFrame, config: LeagueConfig) -> pd.DataFrame:
    """Produce league-specific value, floor, upside, scarcity and risk scores.

    League scoring is applied *before* replacement levels are calculated whenever component
    projections are available. Generic season-points inputs remain supported, but the output
    marks those rows as ``generic_points_fallback`` so downstream product surfaces and model
    gates can distinguish structural league awareness from scoring-exact valuation.
    """
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
    data = prepare_league_scoring_quantiles(data, config)
    q10_col = "valuation_points_q10"
    q50_col = "valuation_points_q50"
    q90_col = "valuation_points_q90"

    replacements = calculate_replacement_levels(data, config, value_column=q50_col)
    ranks = replacement_ranks(data, config, value_column=q50_col)
    starter_counts = starter_allocation(data, config, value_column=q50_col)
    data["replacement_points"] = data["position"].map(replacements).fillna(0.0)
    data["replacement_rank"] = data["position"].map(ranks).fillna(1).astype(int)
    data["league_starter_demand"] = data["position"].map(starter_counts).fillna(0).astype(int)
    data["vorp"] = data[q50_col] - data["replacement_points"]
    data["floor_vorp"] = data[q10_col] - data["replacement_points"]
    data["upside_vorp"] = data[q90_col] - data["replacement_points"]
    data["uncertainty"] = data[q90_col] - data[q10_col]
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
        data["schedule_score"]
        if "schedule_score" in data
        else pd.Series(0.0, index=data.index),
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

    # Backwards-compatible relative VORP remains available for existing product surfaces.
    # ``dynamic_scarcity_score`` below is the better representation of the positional curve.
    positive_vorp = data["vorp"].clip(lower=0.0)
    scale = positive_vorp.groupby(data["position"]).transform("max").replace(0.0, np.nan)
    data["relative_vorp_score"] = (positive_vorp / scale).fillna(0.0).clip(0, 1)
    data["scarcity_score"] = data["relative_vorp_score"]
    data = _add_position_curve_features(data)

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
