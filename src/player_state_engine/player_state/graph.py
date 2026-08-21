from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import score_simulation_draws
from player_state_engine.player_state.core import RolePosterior, StateEstimate


@dataclass(frozen=True, slots=True)
class TeamVolumeState:
    dropbacks_mean: float
    dropbacks_sd: float
    rushes_mean: float
    rushes_sd: float
    red_zone_plays_mean: float = 7.0
    red_zone_plays_sd: float = 2.0

    def __post_init__(self) -> None:
        if min(self.dropbacks_mean, self.rushes_mean, self.red_zone_plays_mean) < 0:
            raise ValueError("team volume means must be nonnegative")
        if min(self.dropbacks_sd, self.rushes_sd, self.red_zone_plays_sd) < 0:
            raise ValueError("team volume standard deviations must be nonnegative")


@dataclass(frozen=True, slots=True)
class ExecutionState:
    catch_rate: float = 0.66
    yards_per_reception: float = 11.0
    yards_per_carry: float = 4.3
    completion_rate: float = 0.66
    passing_yards_per_completion: float = 11.5
    pass_td_rate: float = 0.050
    interception_rate: float = 0.024
    receiving_td_rate_per_target: float = 0.055
    rushing_td_rate_per_carry: float = 0.030
    sack_rate: float = 0.065
    scramble_rate: float = 0.055
    qb_rush_yards_per_carry: float = 5.2
    efficiency_cv: float = 0.32

    def __post_init__(self) -> None:
        for name in (
            "catch_rate",
            "completion_rate",
            "pass_td_rate",
            "interception_rate",
            "receiving_td_rate_per_target",
            "rushing_td_rate_per_carry",
            "sack_rate",
            "scramble_rate",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if min(
            self.yards_per_reception,
            self.yards_per_carry,
            self.passing_yards_per_completion,
            self.qb_rush_yards_per_carry,
            self.efficiency_cv,
        ) < 0:
            raise ValueError("execution efficiencies must be nonnegative")


@dataclass(frozen=True, slots=True)
class PlayerStateSnapshot:
    player_id: str
    position: str
    role: RolePosterior
    team_volume: TeamVolumeState
    execution: ExecutionState
    p_active: float = 0.98
    limited_probability: float = 0.0
    limited_role_multiplier: float = 0.70
    environment_mean: float = 1.0
    environment_sd: float = 0.08
    residual_efficiency_sd: float = 0.06
    team: str | None = None
    opponent: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.p_active) <= 1.0:
            raise ValueError("p_active must be between 0 and 1")
        if not 0.0 <= float(self.limited_probability) <= 1.0:
            raise ValueError("limited_probability must be between 0 and 1")
        if not 0.0 <= float(self.limited_role_multiplier) <= 1.0:
            raise ValueError("limited_role_multiplier must be between 0 and 1")
        if self.environment_mean <= 0 or self.environment_sd < 0 or self.residual_efficiency_sd < 0:
            raise ValueError("environment and residual scale parameters are invalid")


@dataclass(frozen=True, slots=True)
class UncertaintyBreakdown:
    total_variance: float
    availability: float
    team_volume: float
    role_opportunity: float
    execution: float
    environment: float
    residual_model: float
    method: str = "one_component_fixed_variance_reduction"

    def as_dict(self) -> dict[str, float | str]:
        return {
            "total_variance": self.total_variance,
            "availability": self.availability,
            "team_volume": self.team_volume,
            "role_opportunity": self.role_opportunity,
            "execution": self.execution,
            "environment": self.environment,
            "residual_model": self.residual_model,
            "method": self.method,
        }


def _state_or_default(role: RolePosterior, metric: str, default: float) -> StateEstimate:
    state = role.states.get(metric)
    if state is not None:
        return state
    return StateEstimate(default, default, default, default, 2.0, 0.0, 0.0)


def _sample_beta_state(
    rng: np.random.Generator,
    state: StateEstimate,
    size: int,
    *,
    fixed: bool,
) -> np.ndarray:
    mean = float(np.clip(state.mean, 1e-6, 1.0 - 1e-6))
    if fixed:
        return np.full(size, mean, dtype=float)
    strength = max(float(state.effective_sample_size), 2.0)
    alpha = max(mean * strength, 1e-3)
    beta = max((1.0 - mean) * strength, 1e-3)
    return rng.beta(alpha, beta, size=size)


def _normal_count(
    rng: np.random.Generator,
    mean: float,
    sd: float,
    size: int,
    *,
    fixed: bool,
) -> np.ndarray:
    if fixed or sd <= 0:
        return np.full(size, int(round(mean)), dtype=int)
    return np.maximum(np.rint(rng.normal(mean, sd, size=size)), 0).astype(int)


def _efficiency_total(
    rng: np.random.Generator,
    count: np.ndarray,
    mean_per_event: float,
    cv: float,
    *,
    fixed: bool,
) -> np.ndarray:
    count_float = count.astype(float)
    expected = count_float * float(mean_per_event)
    if fixed or cv <= 0:
        return np.maximum(expected, 0.0)
    sd = np.sqrt(np.maximum(count_float, 1.0)) * float(mean_per_event) * float(cv)
    sampled = rng.normal(expected, sd)
    return np.where(count > 0, np.maximum(sampled, 0.0), 0.0)


class PlayerStateGraph:
    """Coherent Monte Carlo player forecast built from explicit latent football states.

    This is a research challenger. It does not replace the production direct quantile bundle.
    Draws are generated as football statistics first and are only then transformed through the
    league's exact scoring weights.
    """

    COMPONENTS = (
        "availability",
        "team_volume",
        "role_opportunity",
        "execution",
        "environment",
        "residual_model",
    )

    def __init__(self, league: LeagueConfig) -> None:
        self.league = league

    def simulate(
        self,
        snapshot: PlayerStateSnapshot,
        *,
        simulations: int = 2000,
        seed: int = 42,
        fixed_components: Iterable[str] = (),
    ) -> pd.DataFrame:
        simulations = int(simulations)
        if simulations <= 0:
            raise ValueError("simulations must be positive")
        fixed = set(fixed_components)
        unknown = fixed - set(self.COMPONENTS)
        if unknown:
            raise ValueError(f"Unknown fixed uncertainty components: {sorted(unknown)}")

        seed_sequence = np.random.SeedSequence(int(seed))
        rng_availability, rng_volume, rng_role, rng_execution, rng_environment, rng_residual = [
            np.random.default_rng(child) for child in seed_sequence.spawn(6)
        ]
        position = str(snapshot.position).upper()

        if "availability" in fixed:
            active_factor = np.full(simulations, float(snapshot.p_active), dtype=float)
            limited_factor = np.full(
                simulations,
                1.0 - float(snapshot.limited_probability) * (1.0 - snapshot.limited_role_multiplier),
                dtype=float,
            )
            active_indicator = np.ones(simulations, dtype=int)
        else:
            active_indicator = (
                rng_availability.random(simulations) < float(snapshot.p_active)
            ).astype(int)
            limited = (
                rng_availability.random(simulations) < float(snapshot.limited_probability)
            ).astype(float)
            limited_factor = 1.0 - limited * (1.0 - float(snapshot.limited_role_multiplier))
            active_factor = active_indicator.astype(float)

        fixed_volume = "team_volume" in fixed
        dropbacks = _normal_count(
            rng_volume,
            snapshot.team_volume.dropbacks_mean,
            snapshot.team_volume.dropbacks_sd,
            simulations,
            fixed=fixed_volume,
        )
        team_rushes = _normal_count(
            rng_volume,
            snapshot.team_volume.rushes_mean,
            snapshot.team_volume.rushes_sd,
            simulations,
            fixed=fixed_volume,
        )
        red_zone_plays = _normal_count(
            rng_volume,
            snapshot.team_volume.red_zone_plays_mean,
            snapshot.team_volume.red_zone_plays_sd,
            simulations,
            fixed=fixed_volume,
        )

        fixed_role = "role_opportunity" in fixed
        route_share = _sample_beta_state(
            rng_role,
            _state_or_default(snapshot.role, "route_participation", 0.5),
            simulations,
            fixed=fixed_role,
        )
        target_share = _sample_beta_state(
            rng_role,
            _state_or_default(snapshot.role, "target_share", 0.1),
            simulations,
            fixed=fixed_role,
        )
        carry_share = _sample_beta_state(
            rng_role,
            _state_or_default(snapshot.role, "carry_share", 0.05),
            simulations,
            fixed=fixed_role,
        )
        red_zone_share = _sample_beta_state(
            rng_role,
            _state_or_default(snapshot.role, "red_zone_share", 0.1),
            simulations,
            fixed=fixed_role,
        )
        goal_line_share = _sample_beta_state(
            rng_role,
            _state_or_default(snapshot.role, "goal_line_share", 0.05),
            simulations,
            fixed=fixed_role,
        )
        role_multiplier = np.clip(limited_factor, 0.0, 1.0)
        route_share = np.clip(route_share * role_multiplier, 0.0, 1.0)
        target_share = np.clip(target_share * role_multiplier, 0.0, 1.0)
        carry_share = np.clip(carry_share * role_multiplier, 0.0, 1.0)
        red_zone_share = np.clip(red_zone_share * role_multiplier, 0.0, 1.0)
        goal_line_share = np.clip(goal_line_share * role_multiplier, 0.0, 1.0)

        if "environment" in fixed:
            environment = np.full(simulations, float(snapshot.environment_mean), dtype=float)
        else:
            environment = np.clip(
                rng_environment.normal(
                    snapshot.environment_mean, snapshot.environment_sd, size=simulations
                ),
                0.65,
                1.35,
            )
        if "residual_model" in fixed:
            residual = np.ones(simulations, dtype=float)
        else:
            residual = np.clip(
                rng_residual.normal(1.0, snapshot.residual_efficiency_sd, size=simulations),
                0.70,
                1.30,
            )
        efficiency_multiplier = environment * residual
        execution = snapshot.execution
        fixed_execution = "execution" in fixed

        output = pd.DataFrame(
            {
                "simulation_id": np.arange(simulations, dtype=int),
                "player_id": str(snapshot.player_id),
                "position": position,
                "team": snapshot.team,
                "opponent": snapshot.opponent,
                "active": active_indicator,
                "team_dropbacks": dropbacks,
                "team_rushes": team_rushes,
                "team_red_zone_plays": red_zone_plays,
                "routes": np.zeros(simulations, dtype=float),
                "targets": np.zeros(simulations, dtype=float),
                "receptions": np.zeros(simulations, dtype=float),
                "carries": np.zeros(simulations, dtype=float),
                "passing_attempts": np.zeros(simulations, dtype=float),
                "passing_completions": np.zeros(simulations, dtype=float),
                "passing_yards": np.zeros(simulations, dtype=float),
                "passing_tds": np.zeros(simulations, dtype=float),
                "interceptions": np.zeros(simulations, dtype=float),
                "rushing_yards": np.zeros(simulations, dtype=float),
                "rushing_tds": np.zeros(simulations, dtype=float),
                "receiving_yards": np.zeros(simulations, dtype=float),
                "receiving_tds": np.zeros(simulations, dtype=float),
                "fumbles": np.zeros(simulations, dtype=float),
                "environment_multiplier": environment,
            }
        )

        if position == "QB":
            sack_rate = np.clip(execution.sack_rate / np.maximum(environment, 0.8), 0.0, 0.30)
            if fixed_execution:
                sacks = np.rint(dropbacks * execution.sack_rate).astype(int)
            else:
                sacks = rng_execution.binomial(dropbacks, sack_rate)
            remaining = np.maximum(dropbacks - sacks, 0)
            scramble_rate = np.full(simulations, execution.scramble_rate, dtype=float)
            if fixed_execution:
                scrambles = np.rint(remaining * execution.scramble_rate).astype(int)
            else:
                scrambles = rng_execution.binomial(
                    remaining, np.clip(scramble_rate, 0.0, 0.35)
                )
            # carry_share is defined by the opportunity engine as player carries / team carries.
            # Scrambles are already part of that total rushing share, so they must not be added
            # again as an independent carry source. Cap them to the sampled team rushing total,
            # then ensure the sampled total QB carries are at least the scramble count.
            scrambles = np.minimum(scrambles, team_rushes)
            attempts = np.maximum(remaining - scrambles, 0)
            if fixed_execution:
                completions = np.minimum(
                    np.rint(attempts * execution.completion_rate).astype(int), attempts
                )
                pass_tds = np.minimum(
                    np.rint(attempts * execution.pass_td_rate).astype(int), completions
                )
                incompletions = np.maximum(attempts - completions, 0)
                interceptions = np.minimum(
                    np.rint(attempts * execution.interception_rate).astype(int), incompletions
                )
            else:
                completions = rng_execution.binomial(attempts, execution.completion_rate)
                td_rate_per_attempt = np.clip(
                    execution.pass_td_rate * environment, 0.0, 0.20
                )
                td_rate_per_completion = np.clip(
                    td_rate_per_attempt / max(execution.completion_rate, 1e-6),
                    0.0,
                    1.0,
                )
                pass_tds = rng_execution.binomial(completions, td_rate_per_completion)
                incompletions = np.maximum(attempts - completions, 0)
                interception_rate_per_incompletion = np.clip(
                    execution.interception_rate / max(1.0 - execution.completion_rate, 1e-6),
                    0.0,
                    1.0,
                )
                interceptions = rng_execution.binomial(
                    incompletions, interception_rate_per_incompletion
                )
            passing_yards = _efficiency_total(
                rng_execution,
                completions,
                execution.passing_yards_per_completion,
                execution.efficiency_cv,
                fixed=fixed_execution,
            ) * efficiency_multiplier
            sampled_total_carries = (
                np.rint(team_rushes * carry_share).astype(int)
                if fixed_role
                else rng_role.binomial(team_rushes, np.clip(carry_share, 0.0, 1.0))
            )
            carries = np.minimum(np.maximum(scrambles, sampled_total_carries), team_rushes)
            rushing_yards = _efficiency_total(
                rng_execution,
                carries,
                execution.qb_rush_yards_per_carry,
                execution.efficiency_cv,
                fixed=fixed_execution,
            ) * efficiency_multiplier
            td_probability = np.clip(
                execution.rushing_td_rate_per_carry
                * (0.55 + red_zone_share + goal_line_share),
                0.0,
                0.25,
            )
            rushing_tds = (
                np.rint(carries * td_probability).astype(int)
                if fixed_execution
                else rng_execution.binomial(carries, td_probability)
            )
            output["passing_attempts"] = attempts * active_factor
            output["passing_completions"] = completions * active_factor
            output["passing_yards"] = passing_yards * active_factor
            output["passing_tds"] = pass_tds * active_factor
            output["interceptions"] = interceptions * active_factor
            output["carries"] = carries * active_factor
            output["rushing_yards"] = rushing_yards * active_factor
            output["rushing_tds"] = rushing_tds * active_factor
        else:
            routes = (
                np.rint(dropbacks * route_share).astype(int)
                if fixed_role
                else rng_role.binomial(dropbacks, np.clip(route_share, 0.0, 1.0))
            )
            target_rate_per_route = np.clip(
                target_share / np.maximum(route_share, 0.05), 0.0, 0.75
            )
            targets = (
                np.rint(routes * target_rate_per_route).astype(int)
                if fixed_role
                else rng_role.binomial(routes, target_rate_per_route)
            )
            if fixed_execution:
                receptions = np.minimum(
                    np.rint(targets * execution.catch_rate).astype(int), targets
                )
            else:
                receptions = rng_execution.binomial(targets, execution.catch_rate)
            receiving_yards = _efficiency_total(
                rng_execution,
                receptions,
                execution.yards_per_reception,
                execution.efficiency_cv,
                fixed=fixed_execution,
            ) * efficiency_multiplier
            receiving_td_rate_per_target = np.clip(
                execution.receiving_td_rate_per_target
                * environment
                * (0.60 + red_zone_share),
                0.0,
                0.30,
            )
            if fixed_execution:
                receiving_tds = np.minimum(
                    np.rint(targets * receiving_td_rate_per_target).astype(int),
                    receptions,
                )
            else:
                receiving_td_rate_per_reception = np.clip(
                    receiving_td_rate_per_target / max(execution.catch_rate, 1e-6),
                    0.0,
                    1.0,
                )
                receiving_tds = rng_execution.binomial(
                    receptions, receiving_td_rate_per_reception
                )
            carries = (
                np.rint(team_rushes * carry_share).astype(int)
                if fixed_role
                else rng_role.binomial(team_rushes, np.clip(carry_share, 0.0, 1.0))
            )
            rushing_yards = _efficiency_total(
                rng_execution,
                carries,
                execution.yards_per_carry,
                execution.efficiency_cv,
                fixed=fixed_execution,
            ) * efficiency_multiplier
            rushing_td_probability = np.clip(
                execution.rushing_td_rate_per_carry
                * environment
                * (0.50 + red_zone_share + goal_line_share),
                0.0,
                0.35,
            )
            rushing_tds = (
                np.rint(carries * rushing_td_probability).astype(int)
                if fixed_execution
                else rng_execution.binomial(carries, rushing_td_probability)
            )
            output["routes"] = routes * active_factor
            output["targets"] = targets * active_factor
            output["receptions"] = receptions * active_factor
            output["receiving_yards"] = receiving_yards * active_factor
            output["receiving_tds"] = receiving_tds * active_factor
            output["carries"] = carries * active_factor
            output["rushing_yards"] = rushing_yards * active_factor
            output["rushing_tds"] = rushing_tds * active_factor

        output["graph_source"] = "player_state_graph_research_challenger"
        output["role_label"] = snapshot.role.role_label
        output["role_change_probability"] = snapshot.role.role_change_probability
        return score_simulation_draws(output, self.league)

    def summarize(self, draws: pd.DataFrame) -> dict[str, float]:
        if "league_fantasy_points" not in draws:
            raise ValueError("draws must contain league_fantasy_points")
        points = pd.to_numeric(draws["league_fantasy_points"], errors="coerce").dropna()
        if points.empty:
            raise ValueError("draws do not contain finite fantasy points")
        q10, q50, q90 = np.quantile(points.to_numpy(float), [0.10, 0.50, 0.90])
        return {
            "mean": float(points.mean()),
            "q10": float(q10),
            "q50": float(q50),
            "q90": float(q90),
            "interval_width": float(q90 - q10),
        }

    def decompose_uncertainty(
        self,
        snapshot: PlayerStateSnapshot,
        *,
        simulations: int = 2500,
        seed: int = 42,
    ) -> UncertaintyBreakdown:
        baseline = self.simulate(snapshot, simulations=simulations, seed=seed)
        base_values = baseline["league_fantasy_points"].to_numpy(float)
        total_variance = float(np.var(base_values, ddof=1)) if len(base_values) > 1 else 0.0
        reductions: dict[str, float] = {}
        for component in self.COMPONENTS:
            held = self.simulate(
                snapshot,
                simulations=simulations,
                seed=seed,
                fixed_components={component},
            )
            variance = float(np.var(held["league_fantasy_points"].to_numpy(float), ddof=1))
            reductions[component] = max(total_variance - variance, 0.0)
        reduction_total = sum(reductions.values())
        shares = (
            {
                component: reductions[component] / reduction_total
                for component in self.COMPONENTS
            }
            if reduction_total > 1e-12
            else {component: 0.0 for component in self.COMPONENTS}
        )
        return UncertaintyBreakdown(
            total_variance=total_variance,
            availability=float(shares["availability"]),
            team_volume=float(shares["team_volume"]),
            role_opportunity=float(shares["role_opportunity"]),
            execution=float(shares["execution"]),
            environment=float(shares["environment"]),
            residual_model=float(shares["residual_model"]),
        )
