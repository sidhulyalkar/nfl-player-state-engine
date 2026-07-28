from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig

POSITION_REPLACEMENT_MULTIPLIER = {"QB": 1.0, "RB": 1.0, "WR": 1.0, "TE": 1.0}


def _replacement_rank(position: str, config: LeagueConfig) -> int:
    starters = config.roster_slots.get(position, 0) * config.teams
    flex = config.roster_slots.get("FLEX", 0) * config.teams
    flex_share = {"RB": 0.45, "WR": 0.45, "TE": 0.10}.get(position, 0.0)
    return max(1, int(starters + flex * flex_share + config.replacement_buffer * config.teams))


def calculate_replacement_levels(
    projections: pd.DataFrame, config: LeagueConfig, value_column: str = "season_points_q50"
) -> dict[str, float]:
    levels: dict[str, float] = {}
    for position, group in projections.groupby("position"):
        ranked = group.sort_values(value_column, ascending=False)
        rank = min(_replacement_rank(str(position), config), len(ranked))
        levels[str(position)] = float(ranked.iloc[rank - 1][value_column]) if rank else 0.0
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
    replacements = calculate_replacement_levels(data, config)
    data["replacement_points"] = data["position"].map(replacements).fillna(0.0)
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
    data["decision_value"] = (
        data["availability_probability"]
        * ((1 - risk) * data["floor_vorp"] + 0.5 * data["vorp"] + risk * data["upside_vorp"])
        + 5.0 * data["opportunity_confidence"]
        + 3.0 * data["role_growth_score"]
        + 2.0 * data["schedule_score"]
    )
    data["scarcity_score"] = data.groupby("position")["vorp"].rank(pct=True)
    data["trade_value"] = 100 * data["decision_value"].rank(pct=True)
    data["draft_value"] = data["decision_value"] - pd.to_numeric(
        data["market_cost"] if "market_cost" in data else pd.Series(0.0, index=data.index),
        errors="coerce",
    ).fillna(0.0)
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
