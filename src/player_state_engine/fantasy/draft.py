from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from math import erf, sqrt

import numpy as np
import pandas as pd

from player_state_engine.fantasy.decision_board import DecisionType, build_decision_board
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import prepare_league_scoring_quantiles
from player_state_engine.fantasy.valuation import starter_allocation


@dataclass(slots=True)
class DraftState:
    teams: int
    draft_slot: int
    current_pick: int
    total_rounds: int
    drafted_player_ids: tuple[str, ...] = ()
    roster_player_ids: tuple[str, ...] = ()
    snake: bool = True

    def __post_init__(self) -> None:
        self.teams = max(2, int(self.teams))
        self.draft_slot = min(self.teams, max(1, int(self.draft_slot)))
        self.current_pick = max(1, int(self.current_pick))
        self.total_rounds = max(1, int(self.total_rounds))

    @property
    def max_pick(self) -> int:
        return self.teams * self.total_rounds

    def picks_for_slot(self) -> list[int]:
        picks: list[int] = []
        for round_number in range(1, self.total_rounds + 1):
            if self.snake and round_number % 2 == 0:
                slot = self.teams - self.draft_slot + 1
            else:
                slot = self.draft_slot
            picks.append((round_number - 1) * self.teams + slot)
        return picks

    @property
    def next_pick(self) -> int | None:
        return next((pick for pick in self.picks_for_slot() if pick > self.current_pick), None)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def probability_available_at_pick(adp: float, pick: int | None, adp_sd: float = 8.0) -> float:
    """Approximate probability a player survives to a later pick.

    ADP is treated as the mean of a draft-position distribution where lower values are
    earlier selections. This is intentionally transparent and can later be replaced by
    platform-specific empirical pick distributions.
    """
    if pick is None or not np.isfinite(adp):
        return 0.0
    sd = max(1.0, float(adp_sd))
    z = (float(pick) - float(adp)) / sd
    return float(np.clip(1.0 - _normal_cdf(z), 0.0, 1.0))


def _percentile(series: pd.Series) -> pd.Series:
    if len(series) <= 1:
        return pd.Series(0.5, index=series.index, dtype=float)
    return series.rank(method="average", pct=True).fillna(0.5)


def _roster_counts(board: pd.DataFrame, roster_player_ids: Iterable[str]) -> Counter[str]:
    ids = {str(player_id) for player_id in roster_player_ids}
    if not ids:
        return Counter()
    selected = board[board["player_id"].astype(str).isin(ids)]
    return Counter(selected["position"].astype(str).str.upper())


def _target_roster_counts(projections: pd.DataFrame, config: LeagueConfig) -> dict[str, float]:
    scored = prepare_league_scoring_quantiles(projections, config)
    starter_counts = starter_allocation(scored, config, value_column="valuation_points_q50")
    targets = {position: count / config.teams for position, count in starter_counts.items()}

    # Bench players still matter in deep formats, but not equally across positions. Spread
    # bench demand using starter shares so a 3RB/3WR/3FLEX league correctly asks for depth.
    bench = config.roster_slots.get("BENCH", 0)
    if bench and starter_counts:
        total_starters = sum(starter_counts.values())
        if total_starters:
            for position, count in starter_counts.items():
                targets[position] = targets.get(position, 0.0) + (
                    bench * config.bench_value_weight * count / total_starters
                )
    return targets


def _tier_cliff(board: pd.DataFrame) -> pd.Series:
    cliff = pd.Series(0.0, index=board.index, dtype=float)
    for _, group in board.groupby("position", sort=False):
        ordered = group.sort_values("decision_specific_score", ascending=False)
        values = ordered["decision_specific_score"].astype(float).to_numpy()
        next_values = np.roll(values, -1)
        if len(values):
            next_values[-1] = values[-1]
        drops = np.maximum(0.0, values - next_values)
        cliff.loc[ordered.index] = drops
    return cliff


def _add_dynamic_draft_scarcity(available: pd.DataFrame, state: DraftState) -> pd.DataFrame:
    """Estimate the positional value lost by waiting until the manager's next turn.

    This is an audit/challenger feature in v0.9, not a silently promoted replacement for the
    v0.8 live score. It combines the league's projected replacement curve with the room's
    probability that same-position alternatives disappear before the next selection.
    """
    out = available.copy()
    if out.empty:
        return out

    out["position_supply_remaining"] = 0
    out["expected_position_drafted_before_next"] = 0.0
    out["expected_position_supply_next_pick"] = 0.0
    out["position_wait_value"] = 0.0
    out["position_wait_loss"] = 0.0

    for _, group in out.groupby("position", sort=False):
        ordered = group.sort_values("vorp", ascending=False)
        positive = ordered.loc[ordered["vorp"] > 0].copy()
        supply = len(positive)
        out.loc[group.index, "position_supply_remaining"] = supply
        if positive.empty:
            continue

        urgency = pd.to_numeric(positive["market_urgency"], errors="coerce").fillna(0.5).clip(0, 1)
        expected_taken = float(urgency.sum())
        expected_remaining = max(0.0, supply - expected_taken)
        out.loc[group.index, "expected_position_drafted_before_next"] = expected_taken
        out.loc[group.index, "expected_position_supply_next_pick"] = expected_remaining

        for row_index, row in ordered.iterrows():
            candidate_vorp = max(0.0, float(row.get("vorp", 0.0)))
            other = positive.loc[positive.index != row_index].copy()
            if other.empty or state.next_pick is None:
                wait_value = 0.0
            else:
                survival = pd.to_numeric(
                    other["survival_to_next_pick"], errors="coerce"
                ).fillna(0.5).clip(0, 1)
                other_vorp = pd.to_numeric(other["vorp"], errors="coerce").fillna(0.0).clip(lower=0.0)
                # Probability-weighted maximum is approximated by ordering alternatives and
                # accumulating their chance of being the best survivor. This stays transparent.
                best_survivor_probability = 1.0
                wait_value = 0.0
                for value, probability in sorted(
                    zip(other_vorp, survival, strict=False), reverse=True, key=lambda item: item[0]
                ):
                    contribution = best_survivor_probability * float(probability)
                    wait_value += contribution * float(value)
                    best_survivor_probability *= 1.0 - float(probability)
                    if best_survivor_probability < 1e-4:
                        break
            out.at[row_index, "position_wait_value"] = wait_value
            out.at[row_index, "position_wait_loss"] = max(0.0, candidate_vorp - wait_value)

    out["position_supply_remaining"] = out["position_supply_remaining"].astype(int)
    out["position_wait_loss_percentile"] = _percentile(out["position_wait_loss"])
    curve = pd.to_numeric(
        out["dynamic_scarcity_score"] if "dynamic_scarcity_score" in out else 0.0,
        errors="coerce",
    ).fillna(0.0)
    out["draft_dynamic_scarcity_score"] = (
        0.55 * curve + 0.45 * out["position_wait_loss_percentile"]
    ).clip(0, 1)
    return out


def _draft_reasons(row: pd.Series) -> str:
    reasons: list[str] = []
    if float(row.get("roster_need_score", 0.0)) >= 0.75:
        reasons.append("fills a major roster need")
    if float(row.get("survival_to_next_pick", 1.0)) <= 0.25:
        reasons.append("unlikely to reach your next pick")
    if float(row.get("position_wait_loss_percentile", 0.0)) >= 0.85:
        reasons.append("large positional value loss if you wait")
    if float(row.get("tier_cliff_percentile", 0.0)) >= 0.80:
        reasons.append("tier cliff behind him")
    if float(row.get("vorp_percentile", 0.0)) >= 0.85:
        reasons.append("elite value over replacement")
    if bool(row.get("median_scoring_boost", False)):
        reasons.append("format rewards weekly floor")
    if float(row.get("reach_rounds", 0.0)) >= 1.5:
        reasons.append("market says you can probably wait")
    return ", ".join(reasons[:4]) if reasons else str(row.get("decision_reasons", "projection-led value"))


def build_live_draft_board(
    projections: pd.DataFrame,
    config: LeagueConfig,
    state: DraftState,
    *,
    market_adp_column: str = "market_adp",
    market_adp_sd_column: str = "market_adp_sd",
) -> pd.DataFrame:
    """Rank the best pick *now* for the current league and draft room.

    The production score remains the interpretable v0.8 blend. v0.9 adds a separately exposed
    dynamic-scarcity challenger so historical replay can decide whether it deserves promotion.
    """
    if state.teams != config.teams:
        raise ValueError("DraftState.teams must match LeagueConfig.teams")

    full_board = build_decision_board(projections, config, DecisionType.DRAFT)
    drafted_ids = {str(player_id) for player_id in state.drafted_player_ids}
    available = full_board[~full_board["player_id"].astype(str).isin(drafted_ids)].copy()
    if available.empty:
        return available

    roster_counts = _roster_counts(full_board, state.roster_player_ids)
    targets = _target_roster_counts(projections, config)
    need_scores: list[float] = []
    for position in available["position"].astype(str).str.upper():
        target = max(0.5, float(targets.get(position, 0.0)))
        current = float(roster_counts.get(position, 0))
        need_scores.append(float(np.clip((target - current) / target, -0.5, 1.0)))
    available["roster_need_score"] = need_scores

    available["tier_cliff"] = _tier_cliff(available)
    available["tier_cliff_percentile"] = _percentile(available["tier_cliff"])
    available["vorp_percentile"] = _percentile(available["vorp"])
    available["base_draft_percentile"] = _percentile(available["decision_specific_score"])

    if market_adp_column in available:
        market_adp = pd.to_numeric(available[market_adp_column], errors="coerce")
    elif "market_cost" in available:
        market_adp = pd.to_numeric(available["market_cost"], errors="coerce")
    else:
        market_adp = pd.Series(np.nan, index=available.index, dtype=float)
    available["market_adp"] = market_adp

    if market_adp_sd_column in available:
        adp_sd = pd.to_numeric(available[market_adp_sd_column], errors="coerce").fillna(8.0)
    else:
        # Draft uncertainty broadens deeper into drafts.
        adp_sd = market_adp.fillna(float(state.current_pick)).map(
            lambda value: max(6.0, min(18.0, 5.0 + 0.055 * float(value)))
        )
    available["market_adp_sd"] = adp_sd
    available["survival_to_next_pick"] = [
        probability_available_at_pick(adp, state.next_pick, sd)
        if np.isfinite(adp)
        else 0.5
        for adp, sd in zip(market_adp, adp_sd, strict=False)
    ]
    available["market_urgency"] = 1.0 - available["survival_to_next_pick"]
    available["reach_rounds"] = (
        (available["market_adp"] - state.current_pick) / config.teams
    ).fillna(0.0)
    available = _add_dynamic_draft_scarcity(available, state)

    floor_pct = _percentile(available["floor_vorp"])
    uncertainty_pct = _percentile(available["uncertainty"])
    if config.median_scoring:
        available["median_format_score"] = (
            0.75 * floor_pct + 0.25 * (1.0 - uncertainty_pct)
        ).clip(0, 1)
        available["median_scoring_boost"] = available["median_format_score"] >= 0.75
    else:
        available["median_format_score"] = 0.5
        available["median_scoring_boost"] = False

    weights = {
        "base": 0.54,
        "need": 0.15,
        "urgency": 0.12,
        "tier": 0.08,
        "vorp": 0.07,
        "median": 0.04 if config.median_scoring else 0.0,
    }
    total_weight = sum(weights.values())
    need_component = ((available["roster_need_score"] + 0.5) / 1.5).clip(0, 1)
    available["live_draft_score"] = 100.0 * (
        weights["base"] * available["base_draft_percentile"]
        + weights["need"] * need_component
        + weights["urgency"] * available["market_urgency"]
        + weights["tier"] * available["tier_cliff_percentile"]
        + weights["vorp"] * available["vorp_percentile"]
        + weights["median"] * available["median_format_score"]
    ) / total_weight

    wait_penalty = np.clip((available["reach_rounds"] - 1.0) / 3.0, 0.0, 1.0)
    available["live_draft_score"] -= 4.0 * wait_penalty * available["survival_to_next_pick"]
    available["live_draft_score"] = available["live_draft_score"].clip(0, 100)

    # Challenger keeps the same semantic pieces but swaps static scarcity for the measured
    # projected loss from waiting. It is deliberately not used for draft_action until promoted.
    challenger = 100.0 * (
        0.52 * available["base_draft_percentile"]
        + 0.14 * need_component
        + 0.11 * available["market_urgency"]
        + 0.08 * available["tier_cliff_percentile"]
        + 0.11 * available["draft_dynamic_scarcity_score"]
        + (0.04 if config.median_scoring else 0.0) * available["median_format_score"]
    ) / (1.0 if config.median_scoring else 0.96)
    available["ranking_challenger_score"] = (challenger - 3.0 * wait_penalty).clip(0, 100)
    available["ranking_challenger_delta"] = (
        available["ranking_challenger_score"] - available["live_draft_score"]
    )
    available["ranking_challenger_promoted"] = False

    available["draft_action"] = np.select(
        [
            (available["live_draft_score"] >= 82) & (available["survival_to_next_pick"] <= 0.45),
            available["live_draft_score"] >= 72,
            (available["survival_to_next_pick"] >= 0.70) & (available["reach_rounds"] >= 1.0),
        ],
        ["DRAFT NOW", "TARGET", "WAIT"],
        default="CONSIDER",
    )
    available["draft_reasons"] = available.apply(_draft_reasons, axis=1)
    available["current_pick"] = state.current_pick
    available["next_pick"] = state.next_pick
    available["draft_slot"] = state.draft_slot

    tie_breakers = [column for column in ("player_id", "player_name") if column in available]
    available = available.sort_values(
        ["live_draft_score", *tie_breakers],
        ascending=[False, *([True] * len(tie_breakers))],
        kind="mergesort",
    ).reset_index(drop=True)
    available["live_rank"] = np.arange(1, len(available) + 1, dtype=int)
    available["challenger_rank"] = (
        available["ranking_challenger_score"].rank(method="first", ascending=False).astype(int)
    )
    return available


def draft_state_from_snapshot(
    snapshot: object,
    *,
    draft_slot: int,
    roster_id: str | None = None,
    total_rounds: int | None = None,
) -> DraftState:
    """Build DraftState from a normalized Sleeper/ESPN LeagueSnapshot-like object."""
    metadata = getattr(snapshot, "metadata", {}) or {}
    settings = snapshot.settings
    picks = list(metadata.get("live_draft_picks") or [])
    drafted_ids = tuple(
        str(pick.get("player_id")) for pick in picks if pick.get("player_id") not in {None, ""}
    )
    resolved_roster_id = roster_id or metadata.get("external_roster_id")
    roster_player_ids: list[str] = []
    if resolved_roster_id is not None:
        for pick in picks:
            pick_roster = pick.get("roster_id") or pick.get("team_id")
            if pick_roster is not None and str(pick_roster) == str(resolved_roster_id):
                player_id = pick.get("player_id")
                if player_id not in {None, ""}:
                    roster_player_ids.append(str(player_id))
        try:
            roster = snapshot.roster(str(resolved_roster_id))
            roster_player_ids.extend(
                str(entry.canonical_player_id or entry.platform_player_id) for entry in roster.players
            )
        except (KeyError, AttributeError):
            pass

    active_draft = metadata.get("active_draft") or {}
    if total_rounds is None:
        total_rounds = int((active_draft.get("settings") or {}).get("rounds") or 0)
    if not total_rounds:
        roster_positions = list(getattr(settings, "roster_positions", []) or [])
        total_rounds = max(1, len(roster_positions))

    current_pick = len(picks) + 1
    draft_type = str(getattr(settings, "draft_type", None) or active_draft.get("type") or "snake")
    return DraftState(
        teams=int(settings.teams),
        draft_slot=draft_slot,
        current_pick=current_pick,
        total_rounds=int(total_rounds),
        drafted_player_ids=drafted_ids,
        roster_player_ids=tuple(dict.fromkeys(roster_player_ids)),
        snake=draft_type.lower() in {"snake", "serpentine"},
    )
