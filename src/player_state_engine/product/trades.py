from __future__ import annotations

from itertools import combinations
from math import exp

import numpy as np
import pandas as pd

from player_state_engine.fantasy.decisions import optimize_lineup
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.product.league_picture import attach_ownership, roster_needs
from player_state_engine.product.schemas import (
    LeagueSnapshot,
    TeamTradeImpact,
    TradeAnalysis,
    TradeAnalysisRequest,
    TradeAsset,
    TradeSide,
    TradeSuggestion,
)


def _projection_id_column(frame: pd.DataFrame) -> str:
    for candidate in ("player_id", "canonical_player_id", "platform_player_id"):
        if candidate in frame:
            return candidate
    raise ValueError("Projection table needs player_id, canonical_player_id, or platform_player_id")


def _value_column(frame: pd.DataFrame, horizon: str) -> str:
    candidates = {
        "week": ("one_week_median", "fantasy_points_ppr_q50", "decision_specific_score"),
        "rest_of_season": ("decision_value", "vorp", "season_points_q50"),
        "dynasty": ("decision_specific_score", "trade_value", "upside_vorp"),
    }[horizon]
    for candidate in candidates:
        if candidate in frame:
            return candidate
    raise ValueError(f"No suitable value column for horizon={horizon}")


def _roster_player_ids(snapshot: LeagueSnapshot, roster_id: str) -> list[str]:
    roster = snapshot.roster(roster_id)
    return [
        str(player.canonical_player_id or player.platform_player_id) for player in roster.players
    ]


def _asset_player_ids(assets: list[TradeAsset]) -> list[str]:
    return [str(asset.player_id) for asset in assets if asset.player_id]


def _post_trade_ids(
    snapshot: LeagueSnapshot, request: TradeAnalysisRequest
) -> tuple[list[str], list[str]]:
    before_a = _roster_player_ids(snapshot, request.side_a.roster_id)
    before_b = _roster_player_ids(snapshot, request.side_b.roster_id)
    out_a = set(_asset_player_ids(request.side_a.assets))
    out_b = set(_asset_player_ids(request.side_b.assets))
    after_a = [player_id for player_id in before_a if player_id not in out_a] + sorted(out_b)
    after_b = [player_id for player_id in before_b if player_id not in out_b] + sorted(out_a)
    return after_a, after_b


def _team_metrics(
    player_ids: list[str],
    projections: pd.DataFrame,
    config: LeagueConfig,
    *,
    horizon: str,
) -> dict[str, float]:
    id_column = _projection_id_column(projections)
    indexed = projections.assign(_id=projections[id_column].astype(str)).set_index("_id")
    team = indexed.reindex(player_ids).dropna(how="all").reset_index(drop=True)
    if team.empty:
        return {key: 0.0 for key in ("value", "starter", "floor", "ceiling", "depth", "need")}
    value_column = _value_column(team, horizon)
    team["lineup_score"] = pd.to_numeric(team[value_column], errors="coerce").fillna(0.0)
    lineup = optimize_lineup(team, config, score_column="lineup_score")
    starter_ids = set(lineup.get(id_column, pd.Series(dtype=str)).astype(str))
    bench = (
        team.loc[~team[id_column].astype(str).isin(starter_ids)]
        if id_column in team
        else team.iloc[0:0]
    )
    floor_col = next(
        (c for c in ("floor_vorp", "season_points_q10", "fantasy_points_ppr_q10") if c in team),
        value_column,
    )
    ceiling_col = next(
        (c for c in ("upside_vorp", "season_points_q90", "fantasy_points_ppr_q90") if c in team),
        value_column,
    )
    value = float(pd.to_numeric(team[value_column], errors="coerce").fillna(0).sum())
    starter = float(
        pd.to_numeric(lineup.get("lineup_score", pd.Series(dtype=float)), errors="coerce")
        .fillna(0)
        .sum()
    )
    floor = float(pd.to_numeric(team[floor_col], errors="coerce").fillna(0).sum())
    ceiling = float(pd.to_numeric(team[ceiling_col], errors="coerce").fillna(0).sum())
    depth = float(
        pd.to_numeric(bench.get(value_column, pd.Series(dtype=float)), errors="coerce")
        .fillna(0)
        .nlargest(5)
        .sum()
    )
    by_position = (
        team.groupby("position")[value_column].apply(
            lambda x: pd.to_numeric(x, errors="coerce").fillna(0).nlargest(2).sum()
        )
        if "position" in team
        else pd.Series(dtype=float)
    )
    need_balance = float(by_position.min()) if len(by_position) else 0.0
    return {
        "value": value,
        "starter": starter,
        "floor": floor,
        "ceiling": ceiling,
        "depth": depth,
        "need": need_balance,
    }


def _probability_improves(delta: float, uncertainty: float) -> float:
    scale = max(1.0, uncertainty)
    return float(1.0 / (1.0 + exp(-delta / scale)))


def _impact(
    roster_id: str,
    before: dict[str, float],
    after: dict[str, float],
    uncertainty: float,
) -> TeamTradeImpact:
    delta = after["value"] - before["value"]
    reasons: list[str] = []
    starter_delta = after["starter"] - before["starter"]
    depth_delta = after["depth"] - before["depth"]
    need_delta = after["need"] - before["need"]
    if starter_delta > 0.5:
        reasons.append("starting lineup improves")
    elif starter_delta < -0.5:
        reasons.append("starting lineup weakens")
    if depth_delta > 0.5:
        reasons.append("bench depth improves")
    elif depth_delta < -0.5:
        reasons.append("bench depth declines")
    if need_delta > 0.5:
        reasons.append("positional balance improves")
    if after["ceiling"] - before["ceiling"] > after["floor"] - before["floor"] + 1:
        reasons.append("adds ceiling more than floor")
    if not reasons:
        reasons.append("small roster-level change")
    return TeamTradeImpact(
        roster_id=roster_id,
        before_value=before["value"],
        after_value=after["value"],
        value_delta=delta,
        starter_delta=starter_delta,
        floor_delta=after["floor"] - before["floor"],
        ceiling_delta=after["ceiling"] - before["ceiling"],
        depth_delta=depth_delta,
        positional_need_delta=need_delta,
        probability_improves=_probability_improves(delta, uncertainty),
        reasons=reasons,
    )


def analyze_trade(
    snapshot: LeagueSnapshot,
    projections: pd.DataFrame,
    request: TradeAnalysisRequest,
    config: LeagueConfig,
) -> TradeAnalysis:
    before_a_ids = _roster_player_ids(snapshot, request.side_a.roster_id)
    before_b_ids = _roster_player_ids(snapshot, request.side_b.roster_id)
    after_a_ids, after_b_ids = _post_trade_ids(snapshot, request)
    before_a = _team_metrics(before_a_ids, projections, config, horizon=request.horizon)
    before_b = _team_metrics(before_b_ids, projections, config, horizon=request.horizon)
    after_a = _team_metrics(after_a_ids, projections, config, horizon=request.horizon)
    after_b = _team_metrics(after_b_ids, projections, config, horizon=request.horizon)
    uncertainty_col = "uncertainty" if "uncertainty" in projections else None
    uncertainty = (
        float(pd.to_numeric(projections[uncertainty_col], errors="coerce").median())
        if uncertainty_col
        else 8.0
    )
    impact_a = _impact(request.side_a.roster_id, before_a, after_a, uncertainty)
    impact_b = _impact(request.side_b.roster_id, before_b, after_b, uncertainty)
    gain_a, gain_b = impact_a.value_delta, impact_b.value_delta
    fairness = float(
        np.clip(100 - 12 * abs(gain_a - gain_b) / max(1.0, abs(gain_a) + abs(gain_b)), 0, 100)
    )
    mutual = float(np.clip(50 + 8 * min(gain_a, gain_b), 0, 100))
    combined = 0.55 * min(gain_a, gain_b) + 0.25 * (gain_a + gain_b) + 0.02 * fairness
    if combined >= 4 and min(gain_a, gain_b) >= 0:
        verdict = "strong_accept"
    elif combined >= 1 and min(gain_a, gain_b) >= -0.5:
        verdict = "accept"
    elif abs(gain_a - gain_b) <= 2.0 and min(gain_a, gain_b) >= -2.0:
        verdict = "balanced"
    elif combined <= -4 or min(gain_a, gain_b) <= -5:
        verdict = "strong_decline"
    else:
        verdict = "decline"
    confidence = float(
        np.clip(1.0 - uncertainty / max(20.0, before_a["value"] + before_b["value"]), 0.25, 0.95)
    )
    caveats = [
        "Trade values are league-relative and depend on the supplied projection timestamp.",
        "Correlated injury, playoff, and role-change scenarios should be simulated before final acceptance.",
    ]
    return TradeAnalysis(
        league_id=request.league_id,
        side_a=impact_a,
        side_b=impact_b,
        fairness_score=fairness,
        mutual_benefit_score=mutual,
        confidence=confidence,
        verdict=verdict,
        caveats=caveats,
    )


def suggest_trades(
    snapshot: LeagueSnapshot,
    projections: pd.DataFrame,
    config: LeagueConfig,
    *,
    roster_id: str,
    max_suggestions: int = 12,
    max_assets_per_side: int = 2,
) -> list[TradeSuggestion]:
    owned = attach_ownership(projections, snapshot)
    needs = roster_needs(snapshot, projections)
    target_need = needs.loc[needs["roster_id"].eq(roster_id)].sort_values(
        "need_score", ascending=False
    )
    target_positions = set(target_need.head(2)["position"])
    my_players = owned.loc[owned["owner_roster_id"].eq(roster_id)].copy()
    value_col = _value_column(my_players, "rest_of_season")
    my_surplus_positions = set(target_need.tail(2)["position"])
    my_candidates = my_players.loc[my_players["position"].isin(my_surplus_positions)].nlargest(
        8, value_col
    )
    if my_candidates.empty:
        my_candidates = my_players.nlargest(8, value_col)

    suggestions: list[TradeSuggestion] = []
    for other in snapshot.rosters:
        if other.roster_id == roster_id:
            continue
        their_players = owned.loc[owned["owner_roster_id"].eq(other.roster_id)].copy()
        targets = their_players.loc[their_players["position"].isin(target_positions)].nlargest(
            10, value_col
        )
        if targets.empty:
            continue
        my_sets = [
            (str(row[_projection_id_column(my_candidates)]),) for _, row in my_candidates.iterrows()
        ]
        their_sets = [(str(row[_projection_id_column(targets)]),) for _, row in targets.iterrows()]
        if max_assets_per_side >= 2:
            my_sets += list(combinations([item[0] for item in my_sets[:5]], 2))
            their_sets += list(combinations([item[0] for item in their_sets[:5]], 2))
        for outgoing in my_sets:
            for incoming in their_sets:
                request = TradeAnalysisRequest(
                    league_id=snapshot.identity.league_id,
                    side_a=TradeSide(
                        roster_id=roster_id,
                        assets=[TradeAsset(player_id=player_id) for player_id in outgoing],
                    ),
                    side_b=TradeSide(
                        roster_id=other.roster_id,
                        assets=[TradeAsset(player_id=player_id) for player_id in incoming],
                    ),
                )
                analysis = analyze_trade(snapshot, projections, request, config)
                if analysis.side_a.value_delta < -1.5 or analysis.side_b.value_delta < -1.5:
                    continue
                explanation = (
                    f"{snapshot.roster(roster_id).team_name} gains {analysis.side_a.value_delta:+.1f} "
                    f"league-adjusted value while {other.team_name} gains {analysis.side_b.value_delta:+.1f}; "
                    f"fairness {analysis.fairness_score:.0f}/100."
                )
                suggestions.append(
                    TradeSuggestion(trade=request, analysis=analysis, explanation=explanation)
                )
    suggestions.sort(
        key=lambda suggestion: (
            min(suggestion.analysis.side_a.value_delta, suggestion.analysis.side_b.value_delta),
            suggestion.analysis.fairness_score,
        ),
        reverse=True,
    )
    return suggestions[:max_suggestions]
