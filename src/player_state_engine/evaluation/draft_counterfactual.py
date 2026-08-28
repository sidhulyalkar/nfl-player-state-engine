from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from player_state_engine.fantasy.draft import DraftState, build_live_draft_board
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import required_projection_positions
from player_state_engine.fantasy.valuation import starter_allocation, value_players

SUPPORTED_POLICIES = (
    "market_adp",
    "projected_points",
    "vorp",
    "decision_value",
    "live_draft_score",
)


@dataclass(frozen=True, slots=True)
class CounterfactualDraftSimulationConfig:
    """Research-only assumptions for complete counterfactual draft simulation."""

    simulations: int = 250
    seed: int = 20260828
    opponent_adp_noise_scale: float = 1.0
    opponent_position_need_strength: float = 0.35
    require_complete_required_positions: bool = True
    require_exact_scoring: bool = True
    bench_utility_weight: float = 0.0

    def __post_init__(self) -> None:
        if self.simulations <= 0:
            raise ValueError("simulations must be positive")
        if self.opponent_adp_noise_scale < 0:
            raise ValueError("opponent_adp_noise_scale must be nonnegative")
        if self.opponent_position_need_strength < 0:
            raise ValueError("opponent_position_need_strength must be nonnegative")
        if not 0.0 <= self.bench_utility_weight <= 1.0:
            raise ValueError("bench_utility_weight must be between zero and one")


@dataclass(frozen=True, slots=True)
class CounterfactualPolicySummary:
    policy: str
    simulations: int
    draft_slot: int
    total_rounds: int
    mean_utility: float | None
    median_utility: float | None
    p10_utility: float | None
    p90_utility: float | None
    mean_unfilled_starter_slots: float | None
    market_imputed_fraction: float
    authority: str = "research_counterfactual_simulation_only"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CounterfactualDraftResult:
    policy: str
    selections: pd.DataFrame
    simulation_results: pd.DataFrame
    summary: CounterfactualPolicySummary


@dataclass(slots=True)
class CounterfactualPolicyComparison:
    baseline_policy: str
    policy_summaries: pd.DataFrame
    paired_deltas: pd.DataFrame
    authority: str = "research_counterfactual_simulation_only"
    inference_scope: str = "room_stochasticity_only_not_historical_generalization"


def _canonical_position(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    position = str(value).strip().upper()
    if position in {"D/ST", "DEFENSE"}:
        return "DST"
    if position in {"PK", "KICKER"}:
        return "K"
    return position


def _snake_owner(*, overall_pick: int, teams: int) -> int:
    pick = max(1, int(overall_pick))
    team_count = max(2, int(teams))
    round_number = (pick - 1) // team_count + 1
    offset = (pick - 1) % team_count
    return offset + 1 if round_number % 2 == 1 else team_count - offset


def _prepare_player_pool(
    player_pool: pd.DataFrame,
    league: LeagueConfig,
    *,
    simulation: CounterfactualDraftSimulationConfig,
) -> tuple[pd.DataFrame, float]:
    required = {
        "player_id",
        "player_name",
        "position",
        "season_points_q10",
        "season_points_q50",
        "season_points_q90",
    }
    missing = required - set(player_pool.columns)
    if missing:
        raise ValueError(f"Counterfactual draft pool missing columns: {sorted(missing)}")

    data = player_pool.copy().reset_index(drop=True)
    data["player_id"] = data["player_id"].astype("string").str.strip()
    invalid = data["player_id"].isna() | data["player_id"].eq("")
    if invalid.any():
        raise ValueError("Counterfactual draft pool contains missing player IDs.")
    if data["player_id"].duplicated().any():
        raise ValueError("Counterfactual draft pool must contain unique player IDs.")
    data["position"] = data["position"].map(_canonical_position)
    if data["position"].eq("").any():
        raise ValueError("Counterfactual draft pool contains missing positions.")

    valued = value_players(data, league)
    if simulation.require_exact_scoring:
        fallback = valued["league_scoring_source"].astype(str).eq("generic_points_fallback")
        if fallback.any():
            fallback_positions = tuple(sorted(valued.loc[fallback, "position"].unique()))
            raise ValueError(
                "Counterfactual whole-draft validation requires exact league scoring; "
                f"generic fallback remains for positions {fallback_positions}."
            )

    if simulation.require_complete_required_positions:
        required_positions = set(required_projection_positions(league))
        present_positions = set(valued["position"].dropna().astype(str).str.upper())
        missing_positions = tuple(sorted(required_positions - present_positions))
        if missing_positions:
            raise ValueError(
                "Counterfactual draft pool is incomplete for the league contract; "
                f"missing positions: {missing_positions}."
            )

    if "market_adp" in valued:
        raw_adp = pd.to_numeric(valued["market_adp"], errors="coerce")
    elif "market_cost" in valued:
        raw_adp = pd.to_numeric(valued["market_cost"], errors="coerce")
    else:
        raw_adp = pd.Series(np.nan, index=valued.index, dtype=float)
    fallback_rank = pd.to_numeric(valued["valuation_points_q50"], errors="coerce").rank(
        method="average", ascending=False, na_option="bottom"
    )
    market_imputed = raw_adp.isna()
    valued["counterfactual_market_adp"] = raw_adp.fillna(fallback_rank).astype(float)

    if "market_adp_sd" in valued:
        raw_sd = pd.to_numeric(valued["market_adp_sd"], errors="coerce")
    else:
        raw_sd = pd.Series(np.nan, index=valued.index, dtype=float)
    default_sd = np.clip(
        5.0 + 0.055 * np.maximum(valued["counterfactual_market_adp"].to_numpy(float), 1.0),
        6.0,
        18.0,
    )
    valued["counterfactual_market_adp_sd"] = raw_sd.fillna(
        pd.Series(default_sd, index=valued.index)
    ).clip(lower=0.25)
    return valued.reset_index(drop=True), float(market_imputed.mean())


def _team_position_targets(pool: pd.DataFrame, league: LeagueConfig) -> dict[str, float]:
    allocation = starter_allocation(pool, league, value_column="valuation_points_q50")
    per_team = {
        str(position).upper(): float(count) / float(league.teams)
        for position, count in allocation.items()
        if count > 0
    }
    bench = float(league.roster_slots.get("BENCH", 0)) * float(league.bench_value_weight)
    if bench > 0 and per_team:
        total = sum(per_team.values())
        if total > 0:
            for position in tuple(per_team):
                per_team[position] += bench * per_team[position] / total
    return per_team


def _roster_counts(roster_ids: Iterable[str], pool_by_id: pd.DataFrame) -> Counter[str]:
    identifiers = tuple(str(player_id) for player_id in roster_ids)
    if not identifiers:
        return Counter()
    selected = pool_by_id.loc[pool_by_id["player_id"].isin(identifiers)]
    return Counter(selected["position"].astype(str).str.upper())


def _opponent_choice(
    pool: pd.DataFrame,
    available_mask: np.ndarray,
    *,
    latent_pick: np.ndarray,
    team_roster: list[str],
    position_targets: dict[str, float],
    position_need_strength: float,
) -> int:
    available_indexes = np.flatnonzero(available_mask)
    if not len(available_indexes):
        raise RuntimeError("Opponent attempted to pick from an empty draft pool.")

    counts = _roster_counts(team_roster, pool)
    needs = np.asarray(
        [
            max(position_targets.get(str(pool.iloc[index]["position"]), 0.0) - counts.get(
                str(pool.iloc[index]["position"]), 0
            ), 0.0)
            / max(position_targets.get(str(pool.iloc[index]["position"]), 0.0), 1.0)
            for index in available_indexes
        ],
        dtype=float,
    )
    scale = pool.iloc[available_indexes]["counterfactual_market_adp_sd"].to_numpy(float)
    adjusted = latent_pick[available_indexes] - float(position_need_strength) * needs * scale
    best = np.min(adjusted)
    tied = available_indexes[np.flatnonzero(np.isclose(adjusted, best, rtol=0.0, atol=1e-12))]
    if len(tied) == 1:
        return int(tied[0])
    tied_ids = pool.iloc[tied]["player_id"].astype(str).to_numpy()
    return int(tied[int(np.argmin(tied_ids))])


def _focal_choice(
    pool: pd.DataFrame,
    available_mask: np.ndarray,
    *,
    policy: str,
    league: LeagueConfig,
    draft_slot: int,
    current_pick: int,
    total_rounds: int,
    drafted_ids: list[str],
    focal_roster: list[str],
) -> int:
    available = pool.loc[available_mask].copy()
    if available.empty:
        raise RuntimeError("Focal policy attempted to pick from an empty draft pool.")

    if policy == "live_draft_score":
        state = DraftState(
            teams=league.teams,
            draft_slot=draft_slot,
            current_pick=current_pick,
            total_rounds=total_rounds,
            drafted_player_ids=tuple(drafted_ids),
            roster_player_ids=tuple(focal_roster),
            snake=True,
        )
        board = build_live_draft_board(pool, league, state)
        if board.empty:
            raise RuntimeError("Live draft policy produced an empty board.")
        selected_id = str(board.iloc[0]["player_id"])
    else:
        if policy == "market_adp":
            score_column = "counterfactual_market_adp"
            ascending = True
        elif policy == "projected_points":
            score_column = "valuation_points_q50"
            ascending = False
        elif policy == "vorp":
            score_column = "vorp"
            ascending = False
        elif policy == "decision_value":
            score_column = "decision_value"
            ascending = False
        elif policy.startswith("score:"):
            score_column = policy.split(":", 1)[1]
            if score_column not in available:
                raise ValueError(f"Counterfactual score policy column unavailable: {score_column}")
            ascending = False
        else:
            raise ValueError(
                f"Unsupported focal policy {policy!r}; choose one of {SUPPORTED_POLICIES} or score:COLUMN."
            )
        ordered = available.sort_values(
            [score_column, "player_id"],
            ascending=[ascending, True],
            kind="mergesort",
            na_position="last",
        )
        selected_id = str(ordered.iloc[0]["player_id"])

    matches = np.flatnonzero(pool["player_id"].astype(str).eq(selected_id).to_numpy() & available_mask)
    if len(matches) != 1:
        raise RuntimeError(f"Focal policy selected invalid player identity {selected_id!r}.")
    return int(matches[0])


def _optimize_roster_proxy(
    roster_ids: Iterable[str],
    pool: pd.DataFrame,
    league: LeagueConfig,
    *,
    utility_column: str,
    bench_weight: float,
) -> tuple[float, int, tuple[str, ...]]:
    if utility_column not in pool:
        raise ValueError(f"Roster utility column unavailable: {utility_column}")
    identifiers = {str(player_id) for player_id in roster_ids}
    roster = pool.loc[pool["player_id"].astype(str).isin(identifiers)].copy()
    roster["__utility"] = pd.to_numeric(roster[utility_column], errors="coerce").fillna(0.0)
    roster["__used"] = False
    starters: list[str] = []
    utility = 0.0
    unfilled = 0

    for position, seats in league.direct_starter_slots.items():
        canonical = _canonical_position(position)
        for _ in range(int(seats)):
            candidates = roster.loc[
                (~roster["__used"]) & roster["position"].astype(str).str.upper().eq(canonical)
            ].sort_values(["__utility", "player_id"], ascending=[False, True], kind="mergesort")
            if candidates.empty:
                unfilled += 1
                continue
            chosen = candidates.index[0]
            roster.at[chosen, "__used"] = True
            utility += float(roster.at[chosen, "__utility"])
            starters.append(str(roster.at[chosen, "player_id"]))

    for slot, seats in league.flex_slots.items():
        eligible = {_canonical_position(position) for position in league.flex_eligibility.get(slot, ())}
        for _ in range(int(seats)):
            candidates = roster.loc[
                (~roster["__used"]) & roster["position"].astype(str).str.upper().isin(eligible)
            ].sort_values(["__utility", "player_id"], ascending=[False, True], kind="mergesort")
            if candidates.empty:
                unfilled += 1
                continue
            chosen = candidates.index[0]
            roster.at[chosen, "__used"] = True
            utility += float(roster.at[chosen, "__utility"])
            starters.append(str(roster.at[chosen, "player_id"]))

    if bench_weight > 0:
        bench = roster.loc[~roster["__used"], "__utility"].clip(lower=0.0)
        utility += float(bench.sum()) * float(bench_weight)
    return float(utility), int(unfilled), tuple(starters)


def simulate_counterfactual_draft(
    player_pool: pd.DataFrame,
    league: LeagueConfig,
    *,
    focal_policy: str,
    draft_slot: int,
    total_rounds: int | None = None,
    utility_column: str | None = None,
    simulation: CounterfactualDraftSimulationConfig | None = None,
) -> CounterfactualDraftResult:
    """Run a complete persistent-pool draft with stochastic counterfactual opponents.

    The opponent room is not historical pick replay. Every simulation samples one latent market
    order, then reuses it throughout the draft while roster demand modifies each opponent choice.
    Focal-policy deviations therefore change the pool seen by all later managers. This is the
    causal behavior missing from independent historical decision-set replay.
    """

    cfg = simulation or CounterfactualDraftSimulationConfig()
    if focal_policy not in SUPPORTED_POLICIES and not focal_policy.startswith("score:"):
        raise ValueError(
            f"Unsupported focal policy {focal_policy!r}; choose one of {SUPPORTED_POLICIES} or score:COLUMN."
        )
    if not 1 <= int(draft_slot) <= int(league.teams):
        raise ValueError("draft_slot must be inside the league team count")
    rounds = int(total_rounds or sum(league.roster_slots.values()))
    if rounds <= 0:
        raise ValueError("total_rounds must be positive")

    pool, market_imputed_fraction = _prepare_player_pool(player_pool, league, simulation=cfg)
    total_picks = min(int(league.teams) * rounds, len(pool))
    if total_picks < int(league.teams):
        raise ValueError("Counterfactual draft pool is too small for one complete round.")
    position_targets = _team_position_targets(pool, league)
    centers = pool["counterfactual_market_adp"].to_numpy(float)
    spreads = pool["counterfactual_market_adp_sd"].to_numpy(float)

    selection_rows: list[dict[str, object]] = []
    simulation_rows: list[dict[str, object]] = []
    for simulation_index in range(cfg.simulations):
        rng = np.random.default_rng(int(cfg.seed) + simulation_index * 1009)
        if cfg.opponent_adp_noise_scale == 0:
            latent = centers.copy()
        else:
            latent = rng.normal(
                centers,
                spreads * float(cfg.opponent_adp_noise_scale),
            )
        available = np.ones(len(pool), dtype=bool)
        rosters: dict[int, list[str]] = {slot: [] for slot in range(1, league.teams + 1)}
        drafted_ids: list[str] = []

        for overall_pick in range(1, total_picks + 1):
            owner = _snake_owner(overall_pick=overall_pick, teams=league.teams)
            if owner == int(draft_slot):
                selected_index = _focal_choice(
                    pool,
                    available,
                    policy=focal_policy,
                    league=league,
                    draft_slot=int(draft_slot),
                    current_pick=overall_pick,
                    total_rounds=rounds,
                    drafted_ids=drafted_ids,
                    focal_roster=rosters[owner],
                )
            else:
                selected_index = _opponent_choice(
                    pool,
                    available,
                    latent_pick=latent,
                    team_roster=rosters[owner],
                    position_targets=position_targets,
                    position_need_strength=cfg.opponent_position_need_strength,
                )

            if not available[selected_index]:
                raise RuntimeError("Counterfactual simulation attempted to draft a player twice.")
            available[selected_index] = False
            player_id = str(pool.iloc[selected_index]["player_id"])
            rosters[owner].append(player_id)
            drafted_ids.append(player_id)
            row = pool.iloc[selected_index]
            selection_rows.append(
                {
                    "simulation": simulation_index,
                    "policy": focal_policy,
                    "overall_pick": overall_pick,
                    "round": (overall_pick - 1) // league.teams + 1,
                    "owner_slot": owner,
                    "is_focal": owner == int(draft_slot),
                    "player_id": player_id,
                    "player_name": str(row["player_name"]),
                    "position": str(row["position"]),
                    "market_adp": float(row["counterfactual_market_adp"]),
                    "market_adp_sd": float(row["counterfactual_market_adp_sd"]),
                }
            )

        focal_roster = tuple(rosters[int(draft_slot)])
        utility: float | None = None
        unfilled: int | None = None
        starters: tuple[str, ...] = ()
        if utility_column is not None:
            utility, unfilled, starters = _optimize_roster_proxy(
                focal_roster,
                pool,
                league,
                utility_column=utility_column,
                bench_weight=cfg.bench_utility_weight,
            )
        simulation_rows.append(
            {
                "simulation": simulation_index,
                "policy": focal_policy,
                "focal_roster": list(focal_roster),
                "starter_player_ids": list(starters),
                "roster_utility": utility,
                "unfilled_starter_slots": unfilled,
            }
        )

    selections = pd.DataFrame(selection_rows)
    simulation_results = pd.DataFrame(simulation_rows)
    utilities = pd.to_numeric(simulation_results["roster_utility"], errors="coerce").dropna()
    unfilled_values = pd.to_numeric(
        simulation_results["unfilled_starter_slots"], errors="coerce"
    ).dropna()
    if utilities.empty:
        mean_utility = median_utility = p10_utility = p90_utility = None
    else:
        mean_utility = float(utilities.mean())
        median_utility = float(utilities.median())
        p10_utility = float(np.quantile(utilities, 0.10))
        p90_utility = float(np.quantile(utilities, 0.90))

    summary = CounterfactualPolicySummary(
        policy=focal_policy,
        simulations=cfg.simulations,
        draft_slot=int(draft_slot),
        total_rounds=rounds,
        mean_utility=mean_utility,
        median_utility=median_utility,
        p10_utility=p10_utility,
        p90_utility=p90_utility,
        mean_unfilled_starter_slots=(
            None if unfilled_values.empty else float(unfilled_values.mean())
        ),
        market_imputed_fraction=market_imputed_fraction,
    )
    return CounterfactualDraftResult(
        policy=focal_policy,
        selections=selections,
        simulation_results=simulation_results,
        summary=summary,
    )


def compare_counterfactual_policies(
    player_pool: pd.DataFrame,
    league: LeagueConfig,
    *,
    policies: Iterable[str],
    baseline_policy: str,
    draft_slot: int,
    total_rounds: int | None = None,
    utility_column: str,
    simulation: CounterfactualDraftSimulationConfig | None = None,
) -> CounterfactualPolicyComparison:
    """Compare policies with common room-randomness seeds.

    The returned confidence bands describe only Monte Carlo room stochasticity for this supplied
    environment. They are not evidence that a policy generalizes across historical seasons,
    platforms, formats, or manager populations. Historical qualification must aggregate paired
    policy effects across independently frozen draft environments.
    """

    policy_list = tuple(dict.fromkeys(str(policy) for policy in policies))
    if not policy_list:
        raise ValueError("At least one policy is required.")
    if baseline_policy not in policy_list:
        raise ValueError("baseline_policy must be included in policies.")

    cfg = simulation or CounterfactualDraftSimulationConfig()
    results = {
        policy: simulate_counterfactual_draft(
            player_pool,
            league,
            focal_policy=policy,
            draft_slot=draft_slot,
            total_rounds=total_rounds,
            utility_column=utility_column,
            simulation=cfg,
        )
        for policy in policy_list
    }
    summary = pd.DataFrame([result.summary.as_dict() for result in results.values()])
    baseline = results[baseline_policy].simulation_results[
        ["simulation", "roster_utility"]
    ].rename(columns={"roster_utility": "baseline_utility"})

    paired_parts: list[pd.DataFrame] = []
    for policy, result in results.items():
        current = result.simulation_results[["simulation", "roster_utility"]].rename(
            columns={"roster_utility": "candidate_utility"}
        )
        paired = baseline.merge(current, on="simulation", validate="one_to_one")
        paired["policy"] = policy
        paired["baseline_policy"] = baseline_policy
        paired["utility_delta"] = (
            pd.to_numeric(paired["candidate_utility"], errors="coerce")
            - pd.to_numeric(paired["baseline_utility"], errors="coerce")
        )
        paired_parts.append(paired)
    paired_deltas = pd.concat(paired_parts, ignore_index=True)

    delta_summary: list[dict[str, object]] = []
    for policy, group in paired_deltas.groupby("policy", sort=False):
        values = pd.to_numeric(group["utility_delta"], errors="coerce").dropna().to_numpy(float)
        if not len(values):
            continue
        delta_summary.append(
            {
                "policy": policy,
                "baseline_policy": baseline_policy,
                "mean_utility_delta": float(values.mean()),
                "median_utility_delta": float(np.median(values)),
                "room_stochasticity_ci_low": float(np.quantile(values, 0.025)),
                "room_stochasticity_ci_high": float(np.quantile(values, 0.975)),
                "policy_win_rate": float(np.mean(values > 0.0)),
                "inference_scope": "room_stochasticity_only_not_historical_generalization",
            }
        )
    if delta_summary:
        summary = summary.merge(pd.DataFrame(delta_summary), on="policy", how="left")
    return CounterfactualPolicyComparison(
        baseline_policy=baseline_policy,
        policy_summaries=summary,
        paired_deltas=paired_deltas,
    )
