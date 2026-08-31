from __future__ import annotations

from collections import defaultdict
from math import ceil

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.projection_contracts import select_projection_scoring_contract
from player_state_engine.fantasy.scoring import prepare_league_scoring_quantiles

CORE_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF", "DST")
QUALIFIED_DISTRIBUTION_POLICY = "qualified_distribution"
Q50_ONLY_POLICY = "q50_only"
LEGACY_DISTRIBUTION_POLICY = "legacy_distribution"
QUALIFIED_MEDIAN_POLICY_AUTHORITY = "qualified_team_week_replay"


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


def _decision_quantile_policy(data: pd.DataFrame) -> pd.Series:
    if "decision_quantile_policy" not in data:
        return pd.Series(LEGACY_DISTRIBUTION_POLICY, index=data.index, dtype="string")
    policy = data["decision_quantile_policy"].astype("string").str.strip().str.lower()
    policy = policy.fillna(LEGACY_DISTRIBUTION_POLICY)
    supported = {
        QUALIFIED_DISTRIBUTION_POLICY,
        Q50_ONLY_POLICY,
        LEGACY_DISTRIBUTION_POLICY,
    }
    unknown = sorted(set(policy.dropna().astype(str)) - supported)
    if unknown:
        raise ValueError(f"Unsupported decision_quantile_policy values: {unknown}")
    return policy


def value_players(
    projections: pd.DataFrame,
    config: LeagueConfig,
    *,
    median_policy_authority: str | None = None,
) -> pd.DataFrame:
    """Produce league-specific value, scarcity and authority-aware draft scores.

    The numerical scoring source and the decision-uncertainty policy are intentionally separate.
    An artifact may contain q10/q50/q90 for auditing while authorizing only q50 for decisions. In
    that case the tails remain visible but cannot influence ``decision_value``. Legacy artifacts
    without an explicit policy preserve historical behavior for compatibility, but production
    release gates should require an explicit qualified policy.

    A shared production artifact may contain several scoring contracts. The exact league slice is
    selected before any replacement, scarcity, or decision calculation so PPR and half-PPR rows can
    never interact merely because they share a file.

    Median-game adjustments are fail-closed too. An unvalidated median league receives no hidden
    heuristic bonus. If a separate team-week replay later earns authority, the projection artifact
    must supply its replay-derived ``median_policy_adjustment`` explicitly; the authority token alone
    can never resurrect the old hard-coded floor-VORP coefficient.
    """
    data = select_projection_scoring_contract(projections, config)
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
    if median_policy_authority not in {None, QUALIFIED_MEDIAN_POLICY_AUTHORITY}:
        raise ValueError(f"Unsupported median_policy_authority: {median_policy_authority!r}")

    data["position"] = data["position"].astype(str).str.upper()
    data = prepare_league_scoring_quantiles(data, config)
    data["decision_quantile_policy"] = _decision_quantile_policy(data)
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

    q50_only = data["decision_quantile_policy"].eq(Q50_ONLY_POLICY)
    data["decision_tail_authorized"] = ~q50_only
    data["decision_floor_vorp"] = data["floor_vorp"].where(~q50_only, data["vorp"])
    data["decision_upside_vorp"] = data["upside_vorp"].where(~q50_only, data["vorp"])
    data["decision_uncertainty"] = data["uncertainty"].where(~q50_only, np.nan)

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
    data["decision_risk_preference_applied"] = ~q50_only
    median_policy_applied = bool(
        config.median_scoring and median_policy_authority == QUALIFIED_MEDIAN_POLICY_AUTHORITY
    )
    data["median_policy_applied"] = median_policy_applied
    data["median_policy_authority"] = (
        QUALIFIED_MEDIAN_POLICY_AUTHORITY if median_policy_applied else "none"
    )
    median_adjustment = pd.Series(0.0, index=data.index, dtype=float)
    if median_policy_applied:
        if "median_policy_adjustment" not in data:
            raise ValueError(
                "Qualified median policy requires replay-derived median_policy_adjustment values"
            )
        replay_adjustment = pd.to_numeric(data["median_policy_adjustment"], errors="coerce")
        if replay_adjustment.isna().any():
            raise ValueError(
                "Qualified median policy contains missing or non-numeric median_policy_adjustment values"
            )
        median_adjustment = replay_adjustment.astype(float)
    data["decision_median_adjustment"] = median_adjustment

    data["decision_value"] = (
        data["availability_probability"]
        * (
            (1 - risk) * data["decision_floor_vorp"]
            + 0.5 * data["vorp"]
            + risk * data["decision_upside_vorp"]
        )
        + 5.0 * data["opportunity_confidence"]
        + 3.0 * data["role_growth_score"]
        + 2.0 * data["schedule_score"]
        + data["decision_median_adjustment"]
    )

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
