from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import score_simulation_draws
from player_state_engine.state_graph.types import ForecastQuantiles, PlayerLatentState


@dataclass(slots=True)
class PlayerStateGraphSampler:
    """Generate football-stat draws from explicit latent player states.

    The graph is intentionally transparent and modular. It is a research challenger, not a
    production replacement: every final fantasy draw is derived from sampled football statistics
    and then rescored using the exact league configuration.
    """

    min_team_plays: int = 35
    max_team_plays: int = 95
    target_per_dropback: float = 0.93
    sack_rate_default: float = 0.065

    @staticmethod
    def _sample_nonnegative_normal(
        rng: np.random.Generator,
        mean: float,
        std: float,
        size: int,
    ) -> np.ndarray:
        return np.maximum(rng.normal(float(mean), max(float(std), 1e-6), size=size), 0.0)

    @staticmethod
    def _beta_mean_draws(posterior, rng: np.random.Generator, size: int) -> np.ndarray:
        return np.clip(posterior.sample(rng, size=size), 0.0, 1.0)

    def _team_volume(
        self,
        state: PlayerLatentState,
        rng: np.random.Generator,
        simulations: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        plays = np.rint(
            self._sample_nonnegative_normal(
                rng,
                state.team_volume.plays_mean,
                state.team_volume.plays_std,
                simulations,
            )
        ).astype(int)
        plays = np.clip(plays, self.min_team_plays, self.max_team_plays)
        dropback_rate = self._beta_mean_draws(state.team_volume.dropback_rate, rng, simulations)
        dropbacks = rng.binomial(plays, np.clip(dropback_rate, 0.05, 0.95))
        rushes = np.maximum(plays - dropbacks, 0)
        red_zone_trips = np.rint(
            self._sample_nonnegative_normal(
                rng,
                state.team_volume.red_zone_trips_mean,
                state.team_volume.red_zone_trips_std,
                simulations,
            )
        ).astype(int)
        return plays, dropbacks, rushes, red_zone_trips

    def sample_player(
        self,
        state: PlayerLatentState,
        *,
        simulations: int = 4000,
        seed: int = 42,
    ) -> pd.DataFrame:
        simulations = max(100, int(simulations))
        rng = np.random.default_rng(seed)
        active_probability = self._beta_mean_draws(state.availability.active, rng, simulations)
        active = rng.binomial(1, active_probability).astype(int)
        team_plays, team_dropbacks, team_rushes, red_zone_trips = self._team_volume(
            state, rng, simulations
        )

        rows = pd.DataFrame(
            {
                "simulation": np.arange(simulations, dtype=int),
                "player_id": state.player_id,
                "player_name": state.player_name,
                "team": state.team,
                "opponent": state.opponent,
                "position": state.position.upper(),
                "season": state.season,
                "week": state.week,
                "active": active,
                "team_plays": team_plays,
                "team_dropbacks": team_dropbacks,
                "team_rushes": team_rushes,
                "red_zone_trips": red_zone_trips,
            }
        )
        position = state.position.upper()
        if position == "QB":
            self._sample_qb(rows, state, rng)
        else:
            self._sample_skill(rows, state, rng)

        stat_columns = (
            "passing_yards",
            "passing_tds",
            "interceptions",
            "rushing_yards",
            "rushing_tds",
            "receptions",
            "receiving_yards",
            "receiving_tds",
            "targets",
            "carries",
            "routes",
        )
        inactive = rows["active"].eq(0)
        for column in stat_columns:
            if column not in rows:
                rows[column] = 0.0
            rows.loc[inactive, column] = 0.0
        rows["model_source"] = "player_state_graph_sampler_v1"
        return rows

    def _sample_qb(
        self,
        rows: pd.DataFrame,
        state: PlayerLatentState,
        rng: np.random.Generator,
    ) -> None:
        n = len(rows)
        dropbacks = rows["team_dropbacks"].to_numpy(dtype=int)
        scramble_rate = self._beta_mean_draws(state.execution.scramble_rate, rng, n)
        sack_rate = float(state.environment.get("sack_rate", self.sack_rate_default))
        sack_rate = float(np.clip(sack_rate, 0.0, 0.25))
        scramble_attempts = rng.binomial(dropbacks, np.clip(scramble_rate, 0.0, 0.40))
        remaining = np.maximum(dropbacks - scramble_attempts, 0)
        sacks = rng.binomial(remaining, sack_rate)
        attempts = np.maximum(remaining - sacks, 0)
        completion_rate = self._beta_mean_draws(state.execution.catch_rate, rng, n)
        completions = rng.binomial(attempts, np.clip(completion_rate, 0.30, 0.85))
        pass_yards_per_attempt = self._sample_nonnegative_normal(
            rng,
            state.execution.pass_yards_per_attempt_mean,
            state.execution.pass_yards_per_attempt_std,
            n,
        )
        passing_yards = np.where(
            attempts > 0,
            np.maximum(attempts * pass_yards_per_attempt + rng.normal(0.0, 18.0, n), 0.0),
            0.0,
        )
        pass_td_rate = self._beta_mean_draws(state.execution.passing_td_per_attempt, rng, n)
        passing_tds = rng.binomial(attempts, np.clip(pass_td_rate, 0.0, 0.18))
        int_rate = self._beta_mean_draws(state.execution.interception_per_attempt, rng, n)
        interceptions = rng.binomial(attempts, np.clip(int_rate, 0.0, 0.15))
        rush_eff = self._sample_nonnegative_normal(
            rng,
            state.execution.yards_per_carry_mean,
            state.execution.yards_per_carry_std,
            n,
        )
        rushing_yards = np.where(
            scramble_attempts > 0,
            np.maximum(scramble_attempts * rush_eff + rng.normal(0.0, 4.0, n), 0.0),
            0.0,
        )
        rush_td_rate = self._beta_mean_draws(state.execution.rushing_td_per_carry, rng, n)
        rushing_tds = rng.binomial(scramble_attempts, np.clip(rush_td_rate, 0.0, 0.30))

        rows["pass_attempts"] = attempts
        rows["completions"] = completions
        rows["passing_yards"] = passing_yards
        rows["passing_tds"] = passing_tds
        rows["interceptions"] = interceptions
        rows["carries"] = scramble_attempts
        rows["rushing_yards"] = rushing_yards
        rows["rushing_tds"] = rushing_tds
        rows["targets"] = 0
        rows["receptions"] = 0
        rows["receiving_yards"] = 0.0
        rows["receiving_tds"] = 0
        rows["routes"] = 0

    def _sample_skill(
        self,
        rows: pd.DataFrame,
        state: PlayerLatentState,
        rng: np.random.Generator,
    ) -> None:
        n = len(rows)
        dropbacks = rows["team_dropbacks"].to_numpy(dtype=int)
        team_rushes = rows["team_rushes"].to_numpy(dtype=int)
        route_share = self._beta_mean_draws(state.role.route_participation.posterior, rng, n)
        routes = rng.binomial(dropbacks, np.clip(route_share, 0.0, 1.0))
        target_share = self._beta_mean_draws(state.role.target_share.posterior, rng, n)
        team_targets = rng.binomial(dropbacks, float(np.clip(self.target_per_dropback, 0.5, 1.0)))
        targets = rng.binomial(team_targets, np.clip(target_share, 0.0, 0.60))
        targets = np.minimum(targets, routes)
        catch_rate = self._beta_mean_draws(state.execution.catch_rate, rng, n)
        receptions = rng.binomial(targets, np.clip(catch_rate, 0.15, 0.95))
        receiving_ypt = self._sample_nonnegative_normal(
            rng,
            state.execution.yards_per_target_mean,
            state.execution.yards_per_target_std,
            n,
        )
        receiving_yards = np.where(
            targets > 0,
            np.maximum(targets * receiving_ypt + rng.normal(0.0, 5.0, n), 0.0),
            0.0,
        )
        receiving_td_rate = self._beta_mean_draws(
            state.execution.receiving_td_per_target, rng, n
        )
        red_zone_share = self._beta_mean_draws(state.role.red_zone_share.posterior, rng, n)
        rz_modifier = 1.0 + 0.9 * red_zone_share
        receiving_tds = rng.binomial(
            targets,
            np.clip(receiving_td_rate * rz_modifier, 0.0, 0.35),
        )

        carry_share = self._beta_mean_draws(state.role.carry_share.posterior, rng, n)
        carries = rng.binomial(team_rushes, np.clip(carry_share, 0.0, 0.95))
        rush_eff = self._sample_nonnegative_normal(
            rng,
            state.execution.yards_per_carry_mean,
            state.execution.yards_per_carry_std,
            n,
        )
        rushing_yards = np.where(
            carries > 0,
            np.maximum(carries * rush_eff + rng.normal(0.0, 3.0, n), 0.0),
            0.0,
        )
        rushing_td_rate = self._beta_mean_draws(state.execution.rushing_td_per_carry, rng, n)
        goal_line_share = self._beta_mean_draws(state.role.goal_line_share.posterior, rng, n)
        rushing_tds = rng.binomial(
            carries,
            np.clip(rushing_td_rate * (1.0 + 1.25 * goal_line_share), 0.0, 0.35),
        )

        rows["routes"] = routes
        rows["targets"] = targets
        rows["receptions"] = receptions
        rows["receiving_yards"] = receiving_yards
        rows["receiving_tds"] = receiving_tds
        rows["carries"] = carries
        rows["rushing_yards"] = rushing_yards
        rows["rushing_tds"] = rushing_tds
        rows["passing_yards"] = 0.0
        rows["passing_tds"] = 0
        rows["interceptions"] = 0

    def sample_team(
        self,
        states: Sequence[PlayerLatentState],
        *,
        simulations: int = 3000,
        seed: int = 42,
    ) -> pd.DataFrame:
        """Sample a team jointly so player opportunity shares obey common-volume constraints."""
        if not states:
            return pd.DataFrame()
        teams = {state.team for state in states}
        weeks = {(state.season, state.week) for state in states}
        if len(teams) != 1 or len(weeks) != 1:
            raise ValueError("sample_team requires one team-week")

        simulations = max(100, int(simulations))
        rng = np.random.default_rng(seed)
        reference = states[0]
        plays, dropbacks, rushes, red_zone_trips = self._team_volume(reference, rng, simulations)
        team_targets = rng.binomial(dropbacks, float(np.clip(self.target_per_dropback, 0.5, 1.0)))

        skill_states = [state for state in states if state.position.upper() != "QB"]
        if not skill_states:
            return pd.concat(
                [self.sample_player(state, simulations=simulations, seed=seed + index) for index, state in enumerate(states)],
                ignore_index=True,
            )

        target_raw = np.column_stack(
            [
                self._beta_mean_draws(state.role.target_share.posterior, rng, simulations)
                for state in skill_states
            ]
        )
        carry_raw = np.column_stack(
            [
                self._beta_mean_draws(state.role.carry_share.posterior, rng, simulations)
                for state in skill_states
            ]
        )
        target_probability = target_raw / np.maximum(target_raw.sum(axis=1, keepdims=True), 1e-9)
        carry_probability = carry_raw / np.maximum(carry_raw.sum(axis=1, keepdims=True), 1e-9)

        target_alloc = np.vstack(
            [rng.multinomial(int(total), probs) for total, probs in zip(team_targets, target_probability, strict=True)]
        )
        carry_alloc = np.vstack(
            [rng.multinomial(int(total), probs) for total, probs in zip(rushes, carry_probability, strict=True)]
        )

        pieces: list[pd.DataFrame] = []
        for column, state in enumerate(skill_states):
            active_probability = self._beta_mean_draws(state.availability.active, rng, simulations)
            active = rng.binomial(1, active_probability).astype(int)
            targets = target_alloc[:, column] * active
            carries = carry_alloc[:, column] * active
            route_share = self._beta_mean_draws(state.role.route_participation.posterior, rng, simulations)
            routes = np.maximum(targets, rng.binomial(dropbacks, np.clip(route_share, 0.0, 1.0)))
            catch_rate = self._beta_mean_draws(state.execution.catch_rate, rng, simulations)
            receptions = rng.binomial(targets, np.clip(catch_rate, 0.15, 0.95))
            ypt = self._sample_nonnegative_normal(
                rng,
                state.execution.yards_per_target_mean,
                state.execution.yards_per_target_std,
                simulations,
            )
            ypc = self._sample_nonnegative_normal(
                rng,
                state.execution.yards_per_carry_mean,
                state.execution.yards_per_carry_std,
                simulations,
            )
            rec_td_rate = self._beta_mean_draws(state.execution.receiving_td_per_target, rng, simulations)
            rush_td_rate = self._beta_mean_draws(state.execution.rushing_td_per_carry, rng, simulations)
            red_zone_share = self._beta_mean_draws(state.role.red_zone_share.posterior, rng, simulations)
            goal_line_share = self._beta_mean_draws(state.role.goal_line_share.posterior, rng, simulations)
            piece = pd.DataFrame(
                {
                    "simulation": np.arange(simulations),
                    "player_id": state.player_id,
                    "player_name": state.player_name,
                    "team": state.team,
                    "opponent": state.opponent,
                    "position": state.position.upper(),
                    "season": state.season,
                    "week": state.week,
                    "active": active,
                    "team_plays": plays,
                    "team_dropbacks": dropbacks,
                    "team_rushes": rushes,
                    "red_zone_trips": red_zone_trips,
                    "routes": routes,
                    "targets": targets,
                    "receptions": receptions,
                    "receiving_yards": np.where(
                        targets > 0,
                        np.maximum(targets * ypt + rng.normal(0.0, 5.0, simulations), 0.0),
                        0.0,
                    ),
                    "receiving_tds": rng.binomial(targets, np.clip(rec_td_rate * (1.0 + 0.9 * red_zone_share), 0.0, 0.35)),
                    "carries": carries,
                    "rushing_yards": np.where(
                        carries > 0,
                        np.maximum(carries * ypc + rng.normal(0.0, 3.0, simulations), 0.0),
                        0.0,
                    ),
                    "rushing_tds": rng.binomial(carries, np.clip(rush_td_rate * (1.0 + 1.25 * goal_line_share), 0.0, 0.35)),
                    "passing_yards": 0.0,
                    "passing_tds": 0,
                    "interceptions": 0,
                    "model_source": "joint_team_player_state_graph_sampler_v1",
                }
            )
            pieces.append(piece)

        for index, state in enumerate(state for state in states if state.position.upper() == "QB"):
            qb = self.sample_player(state, simulations=simulations, seed=seed + 10000 + index)
            pieces.append(qb)
        return pd.concat(pieces, ignore_index=True, sort=False)

    @staticmethod
    def score_draws(draws: pd.DataFrame, league: LeagueConfig) -> pd.DataFrame:
        return score_simulation_draws(draws, league)

    @staticmethod
    def summarize(
        draws: pd.DataFrame,
        *,
        value_column: str = "league_fantasy_points",
        source: str = "player_state_graph",
    ) -> ForecastQuantiles:
        if value_column not in draws:
            raise ValueError(f"Missing draw value column: {value_column}")
        values = pd.to_numeric(draws[value_column], errors="coerce").dropna().to_numpy(dtype=float)
        if len(values) < 20:
            raise ValueError("At least 20 valid draws are required")
        q10, q50, q90 = np.quantile(values, [0.10, 0.50, 0.90])
        return ForecastQuantiles(
            q10=float(q10),
            q50=float(q50),
            q90=float(q90),
            mean=float(np.mean(values)),
            source=source,
        )
