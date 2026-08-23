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

    @staticmethod
    def _allocate_with_residual(
        rng: np.random.Generator,
        totals: np.ndarray,
        raw_shares: np.ndarray,
        active: np.ndarray | None = None,
    ) -> np.ndarray:
        """Allocate a shared opportunity pool without inventing 100% modeled coverage.

        Modeled shares retain their natural total when they sum below one. Any unmodeled share
        is assigned to an explicit residual category and then discarded from player-level output.
        If noisy posterior draws sum above one they are proportionally projected back to one.
        """

        shares = np.clip(np.asarray(raw_shares, dtype=float), 0.0, 1.0)
        if shares.ndim != 2:
            raise ValueError("raw_shares must be a simulation-by-player matrix")
        if active is not None:
            shares = shares * np.asarray(active, dtype=float)
        row_sum = shares.sum(axis=1, keepdims=True)
        scale = np.where(row_sum > 1.0, 1.0 / np.maximum(row_sum, 1e-12), 1.0)
        shares = shares * scale
        residual = np.clip(1.0 - shares.sum(axis=1, keepdims=True), 0.0, 1.0)
        probabilities = np.concatenate([shares, residual], axis=1)
        allocations = np.vstack(
            [
                rng.multinomial(int(total), probability)
                for total, probability in zip(totals, probabilities, strict=True)
            ]
        )
        return allocations[:, : shares.shape[1]]

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
        if state.position.upper() == "QB":
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
        sack_rate = float(np.clip(state.environment.get("sack_rate", self.sack_rate_default), 0.0, 0.25))
        scramble_attempts = rng.binomial(dropbacks, np.clip(scramble_rate, 0.0, 0.40))
        remaining = np.maximum(dropbacks - scramble_attempts, 0)
        sacks = rng.binomial(remaining, sack_rate)
        attempts = np.maximum(remaining - sacks, 0)

        completion_probability = np.clip(
            self._beta_mean_draws(state.execution.catch_rate, rng, n), 0.30, 0.85
        )
        completions = rng.binomial(attempts, completion_probability)
        incompletions = np.maximum(attempts - completions, 0)

        pass_yards_per_attempt = self._sample_nonnegative_normal(
            rng,
            state.execution.pass_yards_per_attempt_mean,
            state.execution.pass_yards_per_attempt_std,
            n,
        )
        yards_per_completion = pass_yards_per_attempt / np.maximum(completion_probability, 1e-6)
        passing_yards = np.where(
            completions > 0,
            np.maximum(completions * yards_per_completion + rng.normal(0.0, 18.0, n), 0.0),
            0.0,
        )

        pass_td_per_attempt = np.clip(
            self._beta_mean_draws(state.execution.passing_td_per_attempt, rng, n), 0.0, 0.18
        )
        pass_td_per_completion = np.clip(
            pass_td_per_attempt / np.maximum(completion_probability, 1e-6), 0.0, 1.0
        )
        passing_tds = rng.binomial(completions, pass_td_per_completion)

        int_per_attempt = np.clip(
            self._beta_mean_draws(state.execution.interception_per_attempt, rng, n), 0.0, 0.15
        )
        int_per_incompletion = np.clip(
            int_per_attempt / np.maximum(1.0 - completion_probability, 1e-6), 0.0, 1.0
        )
        interceptions = rng.binomial(incompletions, int_per_incompletion)

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
        targets = np.minimum(
            rng.binomial(team_targets, np.clip(target_share, 0.0, 0.60)), routes
        )
        catch_probability = np.clip(
            self._beta_mean_draws(state.execution.catch_rate, rng, n), 0.15, 0.95
        )
        receptions = rng.binomial(targets, catch_probability)

        receiving_ypt = self._sample_nonnegative_normal(
            rng,
            state.execution.yards_per_target_mean,
            state.execution.yards_per_target_std,
            n,
        )
        yards_per_reception = receiving_ypt / np.maximum(catch_probability, 1e-6)
        receiving_yards = np.where(
            receptions > 0,
            np.maximum(receptions * yards_per_reception + rng.normal(0.0, 5.0, n), 0.0),
            0.0,
        )
        receiving_td_per_target = self._beta_mean_draws(
            state.execution.receiving_td_per_target, rng, n
        )
        red_zone_share = self._beta_mean_draws(state.role.red_zone_share.posterior, rng, n)
        td_per_reception = np.clip(
            receiving_td_per_target * (1.0 + 0.9 * red_zone_share)
            / np.maximum(catch_probability, 1e-6),
            0.0,
            1.0,
        )
        receiving_tds = rng.binomial(receptions, td_per_reception)

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
        """Sample a team with one shared volume world and explicit unmodeled residual share."""

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
        team_targets = rng.binomial(
            dropbacks, float(np.clip(self.target_per_dropback, 0.5, 1.0))
        )

        skill_states = [state for state in states if state.position.upper() != "QB"]
        qb_states = [state for state in states if state.position.upper() == "QB"]
        pieces: list[pd.DataFrame] = []

        if skill_states:
            skill_active = np.column_stack(
                [
                    rng.binomial(
                        1,
                        self._beta_mean_draws(state.availability.active, rng, simulations),
                    )
                    for state in skill_states
                ]
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
            target_alloc = self._allocate_with_residual(
                rng, team_targets, target_raw, active=skill_active
            )
            carry_alloc = self._allocate_with_residual(
                rng, rushes, carry_raw, active=skill_active
            )

            for column, state in enumerate(skill_states):
                active = skill_active[:, column].astype(int)
                targets = target_alloc[:, column]
                carries = carry_alloc[:, column]
                route_share = self._beta_mean_draws(
                    state.role.route_participation.posterior, rng, simulations
                )
                sampled_routes = rng.binomial(dropbacks, np.clip(route_share, 0.0, 1.0)) * active
                routes = np.maximum(targets, sampled_routes)
                catch_probability = np.clip(
                    self._beta_mean_draws(state.execution.catch_rate, rng, simulations),
                    0.15,
                    0.95,
                )
                receptions = rng.binomial(targets, catch_probability)
                ypt = self._sample_nonnegative_normal(
                    rng,
                    state.execution.yards_per_target_mean,
                    state.execution.yards_per_target_std,
                    simulations,
                )
                yards_per_reception = ypt / np.maximum(catch_probability, 1e-6)
                receiving_yards = np.where(
                    receptions > 0,
                    np.maximum(
                        receptions * yards_per_reception + rng.normal(0.0, 5.0, simulations),
                        0.0,
                    ),
                    0.0,
                )
                rec_td_per_target = self._beta_mean_draws(
                    state.execution.receiving_td_per_target, rng, simulations
                )
                red_zone_share = self._beta_mean_draws(
                    state.role.red_zone_share.posterior, rng, simulations
                )
                rec_td_per_reception = np.clip(
                    rec_td_per_target * (1.0 + 0.9 * red_zone_share)
                    / np.maximum(catch_probability, 1e-6),
                    0.0,
                    1.0,
                )
                receiving_tds = rng.binomial(receptions, rec_td_per_reception)
                ypc = self._sample_nonnegative_normal(
                    rng,
                    state.execution.yards_per_carry_mean,
                    state.execution.yards_per_carry_std,
                    simulations,
                )
                rushing_yards = np.where(
                    carries > 0,
                    np.maximum(carries * ypc + rng.normal(0.0, 3.0, simulations), 0.0),
                    0.0,
                )
                rush_td_rate = self._beta_mean_draws(
                    state.execution.rushing_td_per_carry, rng, simulations
                )
                goal_line_share = self._beta_mean_draws(
                    state.role.goal_line_share.posterior, rng, simulations
                )
                rushing_tds = rng.binomial(
                    carries,
                    np.clip(rush_td_rate * (1.0 + 1.25 * goal_line_share), 0.0, 0.35),
                )
                pieces.append(
                    pd.DataFrame(
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
                            "receiving_yards": receiving_yards,
                            "receiving_tds": receiving_tds,
                            "carries": carries,
                            "rushing_yards": rushing_yards,
                            "rushing_tds": rushing_tds,
                            "passing_yards": 0.0,
                            "passing_tds": 0,
                            "interceptions": 0,
                            "model_source": "joint_team_player_state_graph_sampler_v2",
                        }
                    )
                )

        if qb_states:
            qb_active = np.column_stack(
                [
                    rng.binomial(
                        1,
                        self._beta_mean_draws(state.availability.active, rng, simulations),
                    )
                    for state in qb_states
                ]
            )
            qb_snap_raw = np.column_stack(
                [
                    self._beta_mean_draws(state.role.snap_share.posterior, rng, simulations)
                    for state in qb_states
                ]
            )
            qb_dropbacks = self._allocate_with_residual(
                rng, dropbacks, qb_snap_raw, active=qb_active
            )
            for column, state in enumerate(qb_states):
                qb_rows = pd.DataFrame(
                    {
                        "simulation": np.arange(simulations, dtype=int),
                        "player_id": state.player_id,
                        "player_name": state.player_name,
                        "team": state.team,
                        "opponent": state.opponent,
                        "position": "QB",
                        "season": state.season,
                        "week": state.week,
                        "active": qb_active[:, column].astype(int),
                        "team_plays": plays,
                        "team_dropbacks": qb_dropbacks[:, column],
                        "team_rushes": rushes,
                        "red_zone_trips": red_zone_trips,
                    }
                )
                self._sample_qb(qb_rows, state, rng)
                qb_rows["model_source"] = "joint_team_player_state_graph_sampler_v2"
                pieces.append(qb_rows)

        if not pieces:
            return pd.DataFrame()
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
