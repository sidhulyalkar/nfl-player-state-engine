from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from player_state_engine.fantasy.league import LeagueConfig


@dataclass(frozen=True, slots=True)
class SeasonSimulationResult:
    manager_metrics: pd.DataFrame
    weekly_lineups: pd.DataFrame
    simulations: int
    playoff_teams: int
    bracket_policy: str = "reseed_high_vs_low_with_standard_byes"
    lineup_policy: str = "pregame_expected_value"


@dataclass(frozen=True, slots=True)
class RosterStateDelta:
    manager_id: str
    expected_wins_delta: float
    playoff_probability_delta: float
    championship_probability_delta: float
    expected_points_delta: float
    probability_state_improves: float | None = None


def _starter_slots(config: LeagueConfig) -> list[tuple[str, tuple[str, ...]]]:
    slots: list[tuple[str, tuple[str, ...]]] = []
    for position, count in config.direct_starter_slots.items():
        if position in {"K", "DEF", "DST"}:
            continue
        for number in range(count):
            slots.append((f"{position}{number + 1}", (position,)))
    for flex_name, count in config.flex_slots.items():
        eligible = tuple(config.flex_eligibility.get(flex_name, ()))
        for number in range(count):
            slots.append((f"{flex_name}{number + 1}", eligible))
    return slots


def _optimal_lineup(
    group: pd.DataFrame,
    config: LeagueConfig,
    *,
    value_column: str = "league_fantasy_points",
) -> tuple[float, tuple[str, ...]]:
    slots = _starter_slots(config)
    if group.empty or not slots:
        return 0.0, ()
    if value_column not in group:
        raise ValueError(f"lineup group missing value column: {value_column}")
    scores = pd.to_numeric(group[value_column], errors="coerce").fillna(0.0).to_numpy(float)
    positions = group["position"].astype(str).str.upper().to_numpy()
    matrix = np.full((len(group), len(slots)), -1e9, dtype=float)
    for player_index, position in enumerate(positions):
        for slot_index, (_, eligible) in enumerate(slots):
            if position in eligible:
                matrix[player_index, slot_index] = scores[player_index]
    row_indexes, slot_indexes = linear_sum_assignment(-matrix)
    total = 0.0
    starters: list[str] = []
    for player_index, slot_index in zip(row_indexes, slot_indexes, strict=True):
        value = matrix[player_index, slot_index]
        if value <= -1e8:
            continue
        total += float(value)
        starters.append(str(group.iloc[player_index]["player_id"]))
    return total, tuple(starters)


def _validate_draws(draws: pd.DataFrame) -> pd.DataFrame:
    required = {
        "simulation_id",
        "week",
        "player_id",
        "manager_id",
        "position",
        "league_fantasy_points",
    }
    missing = required - set(draws.columns)
    if missing:
        raise ValueError(f"season draws missing columns: {sorted(missing)}")
    data = draws.copy()
    data["simulation_id"] = pd.to_numeric(data["simulation_id"], errors="raise").astype(int)
    data["week"] = pd.to_numeric(data["week"], errors="raise").astype(int)
    data["manager_id"] = data["manager_id"].astype(str)
    data["player_id"] = data["player_id"].astype(str)
    data["position"] = data["position"].astype(str).str.upper()
    data["league_fantasy_points"] = pd.to_numeric(
        data["league_fantasy_points"], errors="coerce"
    ).fillna(0.0)
    duplicates = data.duplicated(["simulation_id", "week", "player_id"], keep=False)
    if duplicates.any():
        raise ValueError("Each player may appear at most once per simulation/week")
    return data


def _pregame_lineup_plan(draws: pd.DataFrame, config: LeagueConfig) -> dict[tuple[int, str], tuple[str, ...]]:
    """Choose starters from information available before a simulated outcome is realized.

    The Monte Carlo mean for each player-week is used as the pregame selection score. This keeps
    lineup decisions fixed across paths and prevents hindsight-optimal/best-ball scoring from
    inflating managed-league win, playoff, and championship probabilities.
    """

    expected = (
        draws.groupby(["week", "manager_id", "player_id", "position"], as_index=False)[
            "league_fantasy_points"
        ]
        .mean()
        .rename(columns={"league_fantasy_points": "pregame_expected_points"})
    )
    plans: dict[tuple[int, str], tuple[str, ...]] = {}
    for (week, manager_id), group in expected.groupby(["week", "manager_id"], sort=False):
        _, starters = _optimal_lineup(group, config, value_column="pregame_expected_points")
        plans[(int(week), str(manager_id))] = starters
    return plans


def _lineup_table(draws: pd.DataFrame, config: LeagueConfig) -> pd.DataFrame:
    plans = _pregame_lineup_plan(draws, config)
    rows: list[dict[str, object]] = []
    for (simulation_id, week, manager_id), group in draws.groupby(
        ["simulation_id", "week", "manager_id"], sort=False
    ):
        starters = plans.get((int(week), str(manager_id)), ())
        starter_ids = set(starters)
        points = float(
            group.loc[group["player_id"].astype(str).isin(starter_ids), "league_fantasy_points"].sum()
        )
        rows.append(
            {
                "simulation_id": int(simulation_id),
                "week": int(week),
                "manager_id": str(manager_id),
                "lineup_points": points,
                "starter_player_ids": starters,
                "lineup_policy": "pregame_expected_value",
            }
        )
    return pd.DataFrame(rows)


def _schedule_pairs(schedule: pd.DataFrame, regular_weeks: set[int]) -> list[tuple[int, str, str]]:
    required = {"week", "manager_id", "opponent_id"}
    missing = required - set(schedule.columns)
    if missing:
        raise ValueError(f"schedule missing columns: {sorted(missing)}")
    seen: set[tuple[int, str, str]] = set()
    pairs: list[tuple[int, str, str]] = []
    for row in schedule.itertuples(index=False):
        week = int(row.week)
        if week not in regular_weeks:
            continue
        manager = str(row.manager_id)
        opponent = str(row.opponent_id)
        low, high = sorted((manager, opponent))
        key = (week, low, high)
        if low == high or key in seen:
            continue
        seen.add(key)
        pairs.append((week, low, high))
    return pairs


def _play_round(
    participants: list[str],
    seed_number: dict[str, int],
    week: int,
    points: dict[tuple[int, str], float],
) -> list[str]:
    participants = sorted(participants, key=lambda manager: seed_number[manager])
    winners: list[str] = []
    left = 0
    right = len(participants) - 1
    while left < right:
        high_seed = participants[left]
        low_seed = participants[right]
        high_points = float(points.get((int(week), high_seed), 0.0))
        low_points = float(points.get((int(week), low_seed), 0.0))
        if high_points == low_points:
            winner = high_seed
        else:
            winner = high_seed if high_points > low_points else low_seed
        winners.append(winner)
        left += 1
        right -= 1
    if left == right:
        winners.append(participants[left])
    return winners


def _reseeded_champion(
    seeds: list[str],
    seed_number: dict[str, int],
    playoff_weeks: tuple[int, ...],
    points: dict[tuple[int, str], float],
) -> str | None:
    alive = list(seeds)
    if len(alive) <= 1:
        return alive[0] if alive else None

    rounds_required = (len(alive) - 1).bit_length()
    if len(playoff_weeks) < rounds_required:
        raise ValueError(
            f"{len(alive)} playoff teams require at least {rounds_required} playoff weeks"
        )

    bracket_size = 1 << rounds_required
    opening_byes = bracket_size - len(alive)
    for round_index, week in enumerate(playoff_weeks[:rounds_required]):
        if len(alive) <= 1:
            break
        alive.sort(key=lambda manager: seed_number[manager])
        if round_index == 0 and opening_byes > 0:
            bye_teams = alive[:opening_byes]
            participants = alive[opening_byes:]
            alive = bye_teams + _play_round(participants, seed_number, week, points)
        else:
            alive = _play_round(alive, seed_number, week, points)

    alive.sort(key=lambda manager: seed_number[manager])
    return alive[0] if alive else None


class FantasySeasonSimulator:
    """League-specific paired Monte Carlo from weekly player draws to title probability.

    Draws remain correlated when the caller generated them with shared football-world sample
    IDs. The simulator applies a single pregame expected-value lineup plan to every Monte Carlo
    path, then scores the realized outcomes, head-to-head matchups, optional league-median games,
    standings, standard opening-round byes, reseeded playoffs, and championship outcomes.
    """

    def __init__(self, config: LeagueConfig, *, playoff_teams: int | None = None) -> None:
        self.config = config
        default_playoff_teams = min(6, max(2, config.teams // 2))
        self.playoff_teams = int(playoff_teams or default_playoff_teams)
        self.playoff_teams = max(1, min(self.playoff_teams, config.teams))

    def simulate(self, draws: pd.DataFrame, schedule: pd.DataFrame) -> SeasonSimulationResult:
        data = _validate_draws(draws)
        lineups = _lineup_table(data, self.config)
        if lineups.empty:
            raise ValueError("No weekly lineups could be formed")
        playoff_weeks = tuple(sorted(int(week) for week in self.config.playoff_weeks))
        regular_weeks = set(int(week) for week in lineups["week"].unique()) - set(playoff_weeks)
        pairs = _schedule_pairs(schedule, regular_weeks)
        managers = sorted(lineups["manager_id"].unique().tolist())
        simulation_ids = sorted(int(value) for value in lineups["simulation_id"].unique())
        accum = {
            manager: {
                "wins": 0.0,
                "points": 0.0,
                "playoffs": 0.0,
                "championships": 0.0,
            }
            for manager in managers
        }

        for simulation_id in simulation_ids:
            current = lineups.loc[lineups["simulation_id"].eq(simulation_id)]
            point_lookup = {
                (int(row.week), str(row.manager_id)): float(row.lineup_points)
                for row in current.itertuples(index=False)
            }
            wins = {manager: 0.0 for manager in managers}
            points_for = {manager: 0.0 for manager in managers}
            for week in regular_weeks:
                week_points = [point_lookup.get((week, manager), 0.0) for manager in managers]
                median = float(np.median(week_points)) if week_points else 0.0
                for manager, value in zip(managers, week_points, strict=True):
                    points_for[manager] += float(value)
                    if self.config.median_scoring:
                        if value > median:
                            wins[manager] += float(self.config.median_game_weight)
                        elif value == median:
                            wins[manager] += 0.5 * float(self.config.median_game_weight)
            for week, manager, opponent in pairs:
                manager_points = point_lookup.get((week, manager), 0.0)
                opponent_points = point_lookup.get((week, opponent), 0.0)
                if manager_points == opponent_points:
                    wins[manager] += 0.5
                    wins[opponent] += 0.5
                elif manager_points > opponent_points:
                    wins[manager] += 1.0
                else:
                    wins[opponent] += 1.0

            seeds = sorted(
                managers,
                key=lambda manager: (-wins[manager], -points_for[manager], manager),
            )[: self.playoff_teams]
            seed_number = {manager: index + 1 for index, manager in enumerate(seeds)}
            champion = _reseeded_champion(seeds, seed_number, playoff_weeks, point_lookup)
            for manager in managers:
                accum[manager]["wins"] += wins[manager]
                accum[manager]["points"] += points_for[manager]
                accum[manager]["playoffs"] += float(manager in seed_number)
                accum[manager]["championships"] += float(manager == champion)

        denominator = max(len(simulation_ids), 1)
        metrics = pd.DataFrame(
            [
                {
                    "manager_id": manager,
                    "expected_wins": accum[manager]["wins"] / denominator,
                    "expected_regular_season_points": accum[manager]["points"] / denominator,
                    "playoff_probability": accum[manager]["playoffs"] / denominator,
                    "championship_probability": accum[manager]["championships"] / denominator,
                }
                for manager in managers
            ]
        ).sort_values(
            ["championship_probability", "playoff_probability", "expected_wins"],
            ascending=False,
        )
        return SeasonSimulationResult(
            manager_metrics=metrics.reset_index(drop=True),
            weekly_lineups=lineups,
            simulations=len(simulation_ids),
            playoff_teams=self.playoff_teams,
        )

    def compare_roster_states(
        self,
        baseline_draws: pd.DataFrame,
        candidate_draws: pd.DataFrame,
        schedule: pd.DataFrame,
        *,
        manager_id: str,
    ) -> RosterStateDelta:
        baseline = self.simulate(baseline_draws, schedule).manager_metrics
        candidate = self.simulate(candidate_draws, schedule).manager_metrics
        manager_id = str(manager_id)
        before = baseline.loc[baseline["manager_id"].astype(str).eq(manager_id)]
        after = candidate.loc[candidate["manager_id"].astype(str).eq(manager_id)]
        if before.empty or after.empty:
            raise ValueError(f"manager_id {manager_id!r} must exist in both roster states")
        before_row = before.iloc[0]
        after_row = after.iloc[0]
        return RosterStateDelta(
            manager_id=manager_id,
            expected_wins_delta=float(after_row["expected_wins"] - before_row["expected_wins"]),
            playoff_probability_delta=float(
                after_row["playoff_probability"] - before_row["playoff_probability"]
            ),
            championship_probability_delta=float(
                after_row["championship_probability"] - before_row["championship_probability"]
            ),
            expected_points_delta=float(
                after_row["expected_regular_season_points"]
                - before_row["expected_regular_season_points"]
            ),
        )
