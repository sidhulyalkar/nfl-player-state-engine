from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from player_state_engine.fantasy.draft import DraftState, build_live_draft_board
from player_state_engine.fantasy.draft_room import DraftRoomSimulationConfig, simulate_draft_room
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.projection_contracts import select_projection_scoring_contract


def _percentile(series: pd.Series, *, ascending: bool = True) -> pd.Series:
    if len(series) <= 1:
        return pd.Series(0.5, index=series.index, dtype=float)
    return series.rank(method="average", pct=True, ascending=ascending).fillna(0.5)


def _numeric_column(frame: pd.DataFrame, name: str, default: float) -> pd.Series:
    if name in frame:
        source = frame[name]
    else:
        source = pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(source, errors="coerce").fillna(default)


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
    if bool(row.get("projection_freshness_hard_fail", False)):
        return "VERIFY"
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
    if float(row.get("room_vs_baseline_survival_gap", 0.0)) > 0.25:
        reasons.append("room model disagrees with baseline survival")
    if float(row.get("uncertainty_percentile", 0.0)) > 0.80:
        reasons.append("qualified projection uncertainty is high")
    if float(row.get("room_survival_standard_error", 0.0)) > 0.03:
        reasons.append("draft-room Monte Carlo is noisy")
    freshness_status = str(row.get("projection_freshness_status", "UNKNOWN"))
    if freshness_status == "STALE":
        reasons.append("projection artifact is stale")
    elif freshness_status == "UNKNOWN":
        reasons.append("projection freshness is unknown")
    return ", ".join(reasons) if reasons else "inputs and independent draft models agree"


def augment_live_draft_board_with_reliability(
    baseline: pd.DataFrame,
    projections: pd.DataFrame,
    config: LeagueConfig,
    state: DraftState,
    *,
    room_simulations: int = 600,
    room_seed: int = 20260820,
    position_need_strength: float = 0.35,
    projection_age_hours: float | None = None,
    max_projection_age_hours: float = 24.0,
) -> pd.DataFrame:
    """Add correlated room diagnostics and fail-closed action guardrails.

    Shared projection artifacts are reduced to the active scoring contract before opponent-position
    counts are derived. Reliability also consumes ``decision_uncertainty`` rather than raw interval
    width, so a q50-only scoring contract cannot be indirectly penalized by unqualified q10/q90.
    Median-game scoring is likewise neutral unless the baseline explicitly declares a separately
    qualified median policy as applied.
    """

    if baseline.empty:
        return baseline.copy()
    required = {"player_id", "position", "live_rank", "live_draft_score", "draft_action"}
    missing = required - set(baseline.columns)
    if missing:
        raise ValueError(f"reliable draft board missing baseline columns: {sorted(missing)}")

    projections = select_projection_scoring_contract(projections, config)
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
    out = baseline.merge(
        room.drop(columns=["position"]),
        on="player_id",
        how="left",
        validate="one_to_one",
    )

    out["room_market_urgency"] = 1.0 - _numeric_column(
        out, "room_survival_to_next_pick", 0.0
    ).clip(0, 1)
    out["room_wait_loss_percentile"] = _percentile(
        _numeric_column(out, "room_position_wait_loss", 0.0)
    )

    base_pct = _numeric_column(out, "base_draft_percentile", 0.5).clip(0, 1)
    need_component = ((_numeric_column(out, "roster_need_score", 0.0) + 0.5) / 1.5).clip(0, 1)
    tier_pct = _numeric_column(out, "tier_cliff_percentile", 0.5).clip(0, 1)
    median_score = _numeric_column(out, "median_format_score", 0.5).clip(0, 1)
    median_policy_applied = (
        bool(out["median_policy_applied"].fillna(False).astype(bool).all())
        if "median_policy_applied" in out
        else False
    )
    median_weight = 0.04 if median_policy_applied else 0.0
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

    baseline_survival = _numeric_column(out, "survival_to_next_pick", 0.0).clip(0, 1)
    room_survival = _numeric_column(out, "room_survival_to_next_pick", 0.0).clip(0, 1)
    out["room_vs_baseline_survival_gap"] = (room_survival - baseline_survival).abs()
    out["room_vs_analytic_survival_gap"] = out["room_vs_baseline_survival_gap"]
    agreement = (1.0 - out["room_vs_baseline_survival_gap"] / 0.50).clip(0, 1)

    scoring_coverage = _numeric_column(out, "league_scoring_coverage", 1.0).clip(0, 1)
    market_quality = (~out["room_market_imputed"].fillna(True).astype(bool)).astype(float)
    uncertainty = _numeric_column(out, "decision_uncertainty", 0.0)
    out["uncertainty_percentile"] = _percentile(uncertainty)
    uncertainty_quality = 1.0 - out["uncertainty_percentile"]
    monte_carlo_quality = (
        1.0 - _numeric_column(out, "room_survival_standard_error", 1.0) / 0.05
    ).clip(0, 1)

    max_age = max(float(max_projection_age_hours), 1e-6)
    if projection_age_hours is None or not np.isfinite(float(projection_age_hours)):
        age_value = np.nan
        freshness_quality = 0.50
        freshness_status = "UNKNOWN"
        hard_freshness_fail = False
    else:
        age_value = max(0.0, float(projection_age_hours))
        freshness_quality = float(np.exp(-age_value / max_age))
        freshness_status = "FRESH" if age_value <= max_age else "STALE"
        hard_freshness_fail = age_value > max_age
    out["projection_age_hours"] = age_value
    out["projection_freshness_score"] = freshness_quality
    out["projection_freshness_status"] = freshness_status
    out["projection_freshness_hard_fail"] = hard_freshness_fail

    out["draft_reliability_score"] = 100.0 * (
        0.20 * scoring_coverage
        + 0.20 * market_quality
        + 0.15 * uncertainty_quality
        + 0.20 * agreement
        + 0.10 * monte_carlo_quality
        + 0.15 * freshness_quality
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
    next_score = ordered["room_challenger_score"].shift(-1).fillna(
        ordered["room_challenger_score"]
    )
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


def build_reliable_live_draft_board(
    projections: pd.DataFrame,
    config: LeagueConfig,
    state: DraftState,
    *,
    room_simulations: int = 600,
    room_seed: int = 20260820,
    position_need_strength: float = 0.35,
    projection_age_hours: float | None = None,
    max_projection_age_hours: float = 24.0,
) -> pd.DataFrame:
    """Build a guarded, league-specific live draft board from the transparent baseline."""

    baseline = build_live_draft_board(projections, config, state)
    return augment_live_draft_board_with_reliability(
        baseline,
        projections,
        config,
        state,
        room_simulations=room_simulations,
        room_seed=room_seed,
        position_need_strength=position_need_strength,
        projection_age_hours=projection_age_hours,
        max_projection_age_hours=max_projection_age_hours,
    )