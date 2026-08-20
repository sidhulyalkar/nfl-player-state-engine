from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from player_state_engine.fantasy.draft import DraftState, build_live_draft_board
from player_state_engine.fantasy.draft_room import (
    DraftRoomSimulationConfig,
    simulate_draft_room,
)
from player_state_engine.fantasy.league import LeagueConfig


def _percentile(series: pd.Series, *, ascending: bool = True) -> pd.Series:
    if len(series) <= 1:
        return pd.Series(0.5, index=series.index, dtype=float)
    return series.rank(method="average", pct=True, ascending=ascending).fillna(0.5)


def _drafted_position_counts(projections: pd.DataFrame, state: DraftState) -> Counter[str]:
    ids = {str(player_id) for player_id in state.drafted_player_ids}
    if not ids or "player_id" not in projections or "position" not in projections:
        return Counter()
    drafted = projections.loc[projections["player_id"].astype(str).isin(ids)]
    return Counter(drafted["position"].astype(str).str.upper())


def _guarded_action(row: pd.Series) -> str:
    confidence = float(row.get("draft_reliability_score", 0.0))
    rank_gap = abs(float(row.get("room_rank_delta", 0.0)))
    baseline = str(row.get("draft_action", "CONSIDER"))
    if confidence < 50.0 or (rank_gap >= 15 and confidence < 70.0):
        return "VERIFY"
    if baseline == "DRAFT NOW" and confidence < 65.0:
        return "TARGET"
    return baseline


def _confidence_reasons(row: pd.Series) -> str:
    reasons: list[str] = []
    if bool(row.get("room_market_imputed", False)):
        reasons.append("market ADP imputed")
    if float(row.get("league_scoring_coverage", 1.0)) < 0.999:
        reasons.append("league scoring only partially resolved")
    if float(row.get("room_vs_analytic_survival_gap", 0.0)) > 0.25:
        reasons.append("room model disagrees with analytic survival")
    if float(row.get("uncertainty_percentile", 0.0)) > 0.80:
        reasons.append("projection uncertainty is high")
    if float(row.get("room_survival_standard_error", 0.0)) > 0.03:
        reasons.append("draft-room Monte Carlo is noisy")
    return ", ".join(reasons) if reasons else "inputs and independent draft models agree"


def build_reliable_live_draft_board(
    projections: pd.DataFrame,
    config: LeagueConfig,
    state: DraftState,
    *,
    room_simulations: int = 600,
    room_seed: int = 20260820,
    position_need_strength: float = 0.35,
) -> pd.DataFrame:
    """Build a guarded, league-specific live draft board.

    The existing live board remains the production baseline. This advisor adds a correlated
    draft-room challenger, model-disagreement diagnostics, and a presentation guardrail. It does
    not silently promote the challenger: ``draft_action`` is preserved and ``guarded_draft_action``
    becomes more conservative only when the evidence supporting the recommendation is weak.
    """

    baseline = build_live_draft_board(projections, config, state)
    if baseline.empty:
        return baseline

    room = simulate_draft_room(
        baseline,
        config,
        current_pick=state.current_pick,
        next_pick=state.next_pick,
        drafted_position_counts=_drafted_position_counts(projections, state),
        simulation=DraftRoomSimulationConfig(
            simulations=int(room_simulations),
            seed=int(room_seed),
            position_need_strength=float(position_need_strength),
        ),
    )
    out = baseline.merge(room.drop(columns=["position"]), on="player_id", how="left", validate="one_to_one")

    out["room_market_urgency"] = 1.0 - pd.to_numeric(
        out["room_survival_to_next_pick"], errors="coerce"
    ).fillna(0.0).clip(0, 1)
    out["room_wait_loss_percentile"] = _percentile(
        pd.to_numeric(out["room_position_wait_loss"], errors="coerce").fillna(0.0)
    )

    base_pct = pd.to_numeric(out.get("base_draft_percentile", 0.5), errors="coerce").fillna(0.5)
    need_component = (
        (pd.to_numeric(out.get("roster_need_score", 0.0), errors="coerce").fillna(0.0) + 0.5) / 1.5
    ).clip(0, 1)
    tier_pct = pd.to_numeric(out.get("tier_cliff_percentile", 0.5), errors="coerce").fillna(0.5)
    median_score = pd.to_numeric(out.get("median_format_score", 0.5), errors="coerce").fillna(0.5)
    median_weight = 0.04 if config.median_scoring else 0.0
    denominator = 0.48 + 0.14 + 0.12 + 0.08 + 0.14 + median_weight
    out["room_challenger_score"] = 100.0 * (
        0.48 * base_pct
        + 0.14 * need_component
        + 0.12 * out["room_market_urgency"]
        + 0.08 * tier_pct
        + 0.14 * out["room_wait_loss_percentile"]
        + median_weight * median_score
    ) / denominator
    out["room_challenger_score"] = out["room_challenger_score"].clip(0, 100)
    out["room_rank"] = out["room_challenger_score"].rank(method="first", ascending=False).astype(int)
    out["room_rank_delta"] = out["live_rank"].astype(int) - out["room_rank"]
    out["room_challenger_promoted"] = False

    analytic_survival = pd.to_numeric(out.get("survival_to_next_pick", 0.0), errors="coerce").fillna(0.0)
    room_survival = pd.to_numeric(out["room_survival_to_next_pick"], errors="coerce").fillna(0.0)
    out["room_vs_analytic_survival_gap"] = (room_survival - analytic_survival).abs()
    agreement = (1.0 - out["room_vs_analytic_survival_gap"] / 0.50).clip(0, 1)

    scoring_coverage = pd.to_numeric(
        out.get("league_scoring_coverage", pd.Series(1.0, index=out.index)), errors="coerce"
    ).fillna(0.0).clip(0, 1)
    market_quality = (~out["room_market_imputed"].fillna(True).astype(bool)).astype(float)
    uncertainty = pd.to_numeric(out.get("uncertainty", 0.0), errors="coerce").fillna(0.0)
    out["uncertainty_percentile"] = _percentile(uncertainty)
    uncertainty_quality = 1.0 - out["uncertainty_percentile"]
    monte_carlo_quality = (
        1.0
        - pd.to_numeric(out["room_survival_standard_error"], errors="coerce").fillna(1.0) / 0.05
    ).clip(0, 1)

    out["draft_reliability_score"] = 100.0 * (
        0.25 * scoring_coverage
        + 0.25 * market_quality
        + 0.20 * uncertainty_quality
        + 0.20 * agreement
        + 0.10 * monte_carlo_quality
    )
    out["draft_reliability_score"] = out["draft_reliability_score"].clip(0, 100)
    out["draft_reliability"] = pd.cut(
        out["draft_reliability_score"],
        bins=[-np.inf, 50.0, 70.0, np.inf],
        labels=["LOW", "MEDIUM", "HIGH"],
        right=False,
    ).astype(str)
    out["draft_reliability_reasons"] = out.apply(_confidence_reasons, axis=1)
    out["guarded_draft_action"] = out.apply(_guarded_action, axis=1)

    ordered = out.sort_values(
        ["room_challenger_score", "live_draft_score", "player_id"],
        ascending=[False, False, True],
        kind="mergesort",
    )
    next_score = ordered["room_challenger_score"].shift(-1).fillna(ordered["room_challenger_score"])
    ordered["room_score_margin_to_next"] = (
        ordered["room_challenger_score"] - next_score
    ).clip(lower=0.0)
    out = out.merge(
        ordered[["player_id", "room_score_margin_to_next"]],
        on="player_id",
        how="left",
        validate="one_to_one",
    )
    return out.sort_values(["live_rank", "player_id"], kind="mergesort").reset_index(drop=True)
