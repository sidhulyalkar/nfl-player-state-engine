from __future__ import annotations

import numpy as np
import pandas as pd


def _num(data: pd.DataFrame, name: str, default: float | pd.Series = 0.0) -> pd.Series:
    source = data[name] if name in data else default
    if not isinstance(source, pd.Series):
        source = pd.Series(source, index=data.index, dtype=float)
    return pd.to_numeric(source, errors="coerce").fillna(
        0.0 if isinstance(default, pd.Series) else default
    )


def _reasons(data: pd.DataFrame) -> pd.Series:
    output: list[str] = []
    for _, row in data.iterrows():
        reasons: list[str] = []
        if row.get("vacated_target_share", 0) > 0.08:
            reasons.append("vacated targets")
        if row.get("vacated_carry_share", 0) > 0.12:
            reasons.append("vacated carries")
        if row.get("depth_promotion_score", 0) > 0.5:
            reasons.append("depth-chart promotion")
        if row.get("role_growth_signal", 0) > 0.4:
            reasons.append("usage rising")
        if row.get("opportunity_route_participation_q50", 0) > 0.70:
            reasons.append("near-every-down routes")
        if row.get("opportunity_carry_share_q50", 0) > 0.35:
            reasons.append("lead backfield share")
        if row.get("scheme_fit_score", 0) > 0.65:
            reasons.append("strong system fit")
        if row.get("teammate_absence_probability", 0) > 0.35:
            reasons.append("teammate availability opening")
        output.append(", ".join(reasons[:4]) if reasons else "monitor role evidence")
    return pd.Series(output, index=data.index)


def rank_high_chance_opportunities(frame: pd.DataFrame) -> pd.DataFrame:
    """Rank role-expansion candidates before fantasy results arrive.

    The score emphasizes opportunity becoming available, a player's ability to
    capture it, and the confidence that the role will be active. It is not a
    pure recent-points leaderboard.
    """
    data = frame.copy()
    active = _num(data, "opportunity_active_probability", 0.8).clip(0, 1)
    snaps = _num(
        data, "opportunity_snap_share_q50", _num(data, "source_snap_share_roll3", 0.5)
    ).clip(0, 1)
    routes = _num(
        data,
        "opportunity_route_participation_q50",
        _num(data, "source_pass_participation_roll3", 0.4),
    ).clip(0, 1)
    target_share = _num(
        data,
        "opportunity_target_share_q50",
        _num(data, "history_actual_target_share_roll3_mean", 0.0),
    ).clip(0, 1)
    carry_share = _num(
        data,
        "opportunity_carry_share_q50",
        _num(data, "history_actual_carry_share_roll3_mean", 0.0),
    ).clip(0, 1)
    red_zone = _num(
        data,
        "opportunity_red_zone_share_q50",
        _num(data, "history_red_zone_opportunity_share_roll3_mean", 0.0),
    ).clip(0, 1)
    target_trend = _num(data, "opportunity_target_trend", 0.0)
    carry_trend = _num(data, "opportunity_carry_trend", 0.0)
    snap_trend = _num(data, "source_snap_share_trend", 0.0)
    depth_rank = _num(
        data, "availability_depth_rank", _num(data, "source_depth_rank_lag1", 3.0)
    ).clip(lower=1)
    prior_depth = _num(data, "source_depth_rank_roll3", depth_rank)
    workload = _num(data, "availability_workload_fraction", 1.0).clip(0, 1)
    vacated_targets = _num(data, "vacated_target_share", 0.0).clip(0, 1)
    vacated_carries = _num(data, "vacated_carry_share", 0.0).clip(0, 1)
    teammate_absence = _num(data, "teammate_absence_probability", 0.0).clip(0, 1)
    scheme = _num(data, "scheme_fit_score", 0.5).clip(0, 1)
    prospect = _num(data, "prospect_prior_score", 0.0).clip(-1, 1)
    uncertainty = _num(data, "opportunity_uncertainty", 0.3).clip(0, 1)

    data["role_growth_signal"] = np.tanh((target_trend + carry_trend + 8 * snap_trend) / 4.0)
    data["depth_promotion_score"] = np.clip(
        (prior_depth - depth_rank) / prior_depth.clip(lower=1), 0, 1
    )
    data["available_opportunity_score"] = (
        0.35 * vacated_targets
        + 0.35 * vacated_carries
        + 0.20 * teammate_absence
        + 0.10 * data["depth_promotion_score"]
    ).clip(0, 1)
    data["role_capture_score"] = (
        0.18 * snaps
        + 0.18 * routes
        + 0.20 * target_share
        + 0.20 * carry_share
        + 0.10 * red_zone
        + 0.08 * scheme
        + 0.04 * np.clip(prospect, 0, 1)
        + 0.02 * (1 / depth_rank)
    ).clip(0, 1)
    data["high_chance_opportunity_score"] = (
        active
        * workload
        * (
            0.50 * data["role_capture_score"]
            + 0.30 * data["available_opportunity_score"]
            + 0.20 * ((data["role_growth_signal"] + 1) / 2)
        )
        * (1.0 - 0.25 * uncertainty)
    ).clip(0, 1)
    data["breakout_probability"] = (
        0.55 * data["high_chance_opportunity_score"]
        + 0.25 * data["available_opportunity_score"]
        + 0.20 * np.clip(prospect, 0, 1)
    ).clip(0, 1)
    data["opportunity_archetype"] = np.select(
        [
            (vacated_targets > 0.08) & (routes > 0.55),
            (vacated_carries > 0.12) & (carry_share > 0.20),
            routes > 0.70,
            carry_share > 0.35,
            data["depth_promotion_score"] > 0.40,
            data["role_growth_signal"] > 0.35,
        ],
        [
            "vacated_target_capture",
            "vacated_backfield_capture",
            "route_everydown",
            "backfield_lead",
            "depth_promoter",
            "role_riser",
        ],
        default="watchlist",
    )
    data["opportunity_reasons"] = _reasons(data)
    return data.sort_values("high_chance_opportunity_score", ascending=False).reset_index(drop=True)
