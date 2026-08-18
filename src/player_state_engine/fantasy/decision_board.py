from __future__ import annotations

from enum import StrEnum

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.valuation import value_players


class DecisionType(StrEnum):
    START_SIT = "start_sit"
    WAIVER = "waiver"
    TRADE = "trade"
    DRAFT = "draft"
    STASH = "stash"
    DYNASTY = "dynasty"


def _num(frame: pd.DataFrame, name: str, default: float | pd.Series = 0.0) -> pd.Series:
    if name in frame:
        source = frame[name]
    elif isinstance(default, pd.Series):
        source = default.reindex(frame.index)
    else:
        source = pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(source, errors="coerce").fillna(0.0 if isinstance(default, pd.Series) else default)


def _percentile(series: pd.Series) -> pd.Series:
    if len(series) <= 1:
        return pd.Series(0.5, index=series.index)
    return series.rank(pct=True).fillna(0.5)


def _reason_codes(data: pd.DataFrame, decision: DecisionType) -> pd.Series:
    output: list[str] = []
    uncertainty_median = float(_num(data, "uncertainty", 0.0).median())
    for _, row in data.iterrows():
        reasons: list[str] = []
        if float(row.get("availability_probability", 1.0)) < 0.75:
            reasons.append("availability risk")
        if float(row.get("role_growth_score", 0.0)) > 0.5:
            reasons.append("role expanding")
        if float(row.get("opportunity_confidence", 0.5)) > 0.7:
            reasons.append("stable opportunity")
        if float(row.get("scheme_fit_score", 0.0)) > 0.6:
            reasons.append("favorable team fit")
        if float(row.get("schedule_score", 0.0)) > 0.5:
            reasons.append("favorable schedule")
        if float(row.get("uncertainty", 0.0)) > uncertainty_median:
            reasons.append("wide outcome range")
        if (
            decision in {DecisionType.STASH, DecisionType.DYNASTY}
            and float(row.get("prospect_prior_score", 0.0)) > 0.4
        ):
            reasons.append("strong prospect prior")
        if decision == DecisionType.DRAFT and float(row.get("market_value_gap", 0.0)) > 6:
            reasons.append("model value ahead of market")
        output.append(", ".join(reasons[:4]) if reasons else "projection-led value")
    return pd.Series(output, index=data.index)


def build_decision_board(
    projections: pd.DataFrame,
    config: LeagueConfig,
    decision: DecisionType | str,
) -> pd.DataFrame:
    """Create a decision-specific fantasy board instead of one universal rating.

    Market ADP is intentionally *not* subtracted from football value. ADP is a draft-timing
    variable, not a fantasy-points unit. Live draft logic consumes ADP separately to estimate
    whether a player will survive to the manager's next selection.
    """
    decision = DecisionType(decision)
    data = value_players(projections, config)

    availability = _num(data, "availability_probability", 1.0).clip(0, 1)
    opportunity = _num(data, "opportunity_confidence", 0.5).clip(0, 1)
    growth = _num(data, "role_growth_score", 0.0)
    schedule = _num(data, "schedule_score", 0.0)
    scheme = _num(data, "scheme_fit_score", 0.0)
    age = _num(data, "age", 27.0)
    prospect = _num(data, "prospect_prior_score", 0.0)
    breakout = _num(data, "breakout_probability", 0.0).clip(0, 1)
    playoff = _num(data, "playoff_schedule_score", schedule)

    data["market_value_gap"] = 0.0
    data["one_week_floor"] = _num(
        data,
        "week_points_q10",
        _num(data, "fantasy_points_ppr_q10", data["season_points_q10"] / 17.0),
    )
    data["one_week_median"] = _num(
        data,
        "week_points_q50",
        _num(data, "fantasy_points_ppr_q50", data["season_points_q50"] / 17.0),
    )
    data["one_week_ceiling"] = _num(
        data,
        "week_points_q90",
        _num(data, "fantasy_points_ppr_q90", data["season_points_q90"] / 17.0),
    )

    if decision == DecisionType.START_SIT:
        risk = float(np.clip(config.risk_preference, 0, 1))
        utility = (
            availability
            * (
                (1 - risk) * data["one_week_floor"]
                + 0.5 * data["one_week_median"]
                + risk * data["one_week_ceiling"]
            )
            + 1.5 * schedule
            + 1.0 * scheme
        )
    elif decision == DecisionType.WAIVER:
        utility = (
            data["vorp"]
            + 7.0 * growth
            + 6.0 * opportunity
            + 5.0 * breakout
            + 2.0 * scheme
            + 2.0 * schedule
        ) * availability
    elif decision == DecisionType.TRADE:
        utility = (
            0.45 * data["floor_vorp"]
            + 0.75 * data["vorp"]
            + 0.45 * data["upside_vorp"]
            + 3.0 * playoff
            + 2.0 * opportunity
            - 0.10 * data["uncertainty"]
        ) * availability
    elif decision == DecisionType.DRAFT:
        utility = (
            data["decision_value"]
            + 8.0 * data["scarcity_score"]
            + 4.0 * opportunity
            + 3.0 * scheme
        )
    elif decision == DecisionType.STASH:
        youth = np.clip((29.0 - age) / 8.0, -0.5, 1.0)
        utility = (
            0.35 * data["upside_vorp"]
            + 10.0 * growth
            + 8.0 * breakout
            + 6.0 * prospect
            + 4.0 * youth
            + 2.0 * scheme
        ) * availability
    else:  # dynasty
        youth = np.clip((30.0 - age) / 10.0, -0.6, 1.0)
        utility = (
            0.35 * data["floor_vorp"]
            + 0.55 * data["vorp"]
            + 0.60 * data["upside_vorp"]
            + 8.0 * prospect
            + 6.0 * breakout
            + 5.0 * youth
            + 3.0 * scheme
        ) * availability

    data["decision_type"] = decision.value
    data["decision_specific_score"] = utility
    data["decision_percentile"] = _percentile(data["decision_specific_score"])
    tie_breakers = [column for column in ("player_id", "player_name") if column in data.columns]
    data = data.sort_values(
        ["decision_specific_score", *tie_breakers],
        ascending=[False, *([True] * len(tie_breakers))],
        kind="mergesort",
    ).reset_index(drop=True)
    data["overall_rank"] = np.arange(1, len(data) + 1, dtype=int)
    data["position_rank"] = data.groupby("position", sort=False).cumcount() + 1
    if "market_adp" in data:
        data["market_value_gap"] = pd.to_numeric(data["market_adp"], errors="coerce") - data["overall_rank"]
    data["decision_reasons"] = _reason_codes(data, decision)
    return data
