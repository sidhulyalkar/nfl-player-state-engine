from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from player_state_engine.fantasy.league import LeagueConfig


@dataclass(slots=True, frozen=True)
class SeasonSimulationSummary:
    manager_id: str
    expected_wins: float
    expected_points: float
    playoff_probability: float
    championship_probability: float
    expected_seed: float


@dataclass(slots=True)
class FantasySeasonSimulator:
    """Correlated rest-of-season fantasy league simulator.

    Input weekly draws are expected to preserve the NFL correlation structure upstream. This
    layer only handles league scoring outcomes: legal lineups, H2H/median wins, standings and a
    deterministic playoff bracket for each Monte Carlo world.
    """

    config: LeagueConfig
    playoff_teams: int | None = None

    def _starter_slots(self) -> list[tuple[str, tuple[str, ...]]]:
        slots: list[tuple[str, tuple[str, ...]]] = []
        for position, count in self.config.direct_starter_slots.items():
            if position in {"K", "DEF", "DST"}:
                continue
            for index in range(count):
                slots.append((f"{position}{index + 1}", (position,)))
        for slot, count in self.config.flex_slots.items():
            eligible = tuple(self.config.flex_eligibility.get(slot, ()))
            for index in range(count):
                slots.append((f"{slot}{index + 1}", eligible))
        return slots

    def _lineup_score(self, roster: pd.DataFrame) -> float:
        if roster.empty:
            return 0.0
        slots = self._starter_slots()
        if not slots:
            return 0.0
        positions = roster["position"].astype(str).str.upper().to_numpy()
        values = pd.to_numeric(roster["fantasy_points"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        matrix = np.full((len(roster), len(slots)), -1e9, dtype=float)
        for player_index, position in enumerate(positions):
            for slot_index, (_, eligible) in enumerate(slots):
                if position in eligible:
                    matrix[player_index, slot_index] = values[player_index]
        rows, columns = linear_sum_assignment(-matrix)
        total = 0.0
        for row, column in zip(rows, columns, strict=True):
            if matrix[row, column] > -1e8:
                total += float(matrix[row, column])
        return total

    def _weekly_scores(
        self,
        draws: pd.DataFrame,
        rosters: pd.DataFrame,
        simulation: int,
        week: int,
    ) -> dict[str, float]:
        world = draws.loc[
            pd.to_numeric(draws["simulation"], errors="coerce").eq(int(simulation))
            & pd.to_numeric(draws["week"], errors="coerce").eq(int(week))
        ]
        merged = rosters.merge(world, on="player_id", how="left", suffixes=("", "_draw"))
        if "position_draw" in merged:
            merged["position"] = merged["position_draw"].fillna(merged.get("position"))
        merged["fantasy_points"] = pd.to_numeric(
            merged.get("fantasy_points"), errors="coerce"
        ).fillna(0.0)
        return {
            str(manager): self._lineup_score(group)
            for manager, group in merged.groupby(merged["manager_id"].astype(str), sort=False)
        }

    def _resolved_playoff_teams(self, team_count: int) -> int:
        if self.playoff_teams is not None:
            value = int(self.playoff_teams)
        else:
            value = 6 if team_count >= 10 else 4
        allowed = [candidate for candidate in (2, 4, 6, 8) if candidate <= team_count]
        if not allowed:
            return min(2, team_count)
        return min(allowed, key=lambda candidate: abs(candidate - value))

    @staticmethod
    def _rank(managers: Iterable[str], wins: dict[str, float], points: dict[str, float]) -> list[str]:
        return sorted(
            (str(manager) for manager in managers),
            key=lambda manager: (wins.get(manager, 0.0), points.get(manager, 0.0), manager),
            reverse=True,
        )

    @staticmethod
    def _winner(a: str, b: str, scores: dict[str, float], seed_order: dict[str, int]) -> str:
        score_a = scores.get(a, 0.0)
        score_b = scores.get(b, 0.0)
        if score_a > score_b:
            return a
        if score_b > score_a:
            return b
        return a if seed_order[a] < seed_order[b] else b

    def _playoff_champion(
        self,
        qualifiers: list[str],
        weekly_scores: dict[int, dict[str, float]],
    ) -> str:
        seed_order = {manager: index + 1 for index, manager in enumerate(qualifiers)}
        weeks = list(self.config.playoff_weeks)
        if len(qualifiers) == 2:
            week = weeks[-1] if weeks else max(weekly_scores)
            return self._winner(qualifiers[0], qualifiers[1], weekly_scores.get(week, {}), seed_order)
        if len(qualifiers) == 4:
            semifinal_week = weeks[-2] if len(weeks) >= 2 else weeks[0]
            final_week = weeks[-1]
            semifinal_scores = weekly_scores.get(semifinal_week, {})
            first = self._winner(qualifiers[0], qualifiers[3], semifinal_scores, seed_order)
            second = self._winner(qualifiers[1], qualifiers[2], semifinal_scores, seed_order)
            return self._winner(first, second, weekly_scores.get(final_week, {}), seed_order)
        if len(qualifiers) == 6:
            if len(weeks) < 3:
                raise ValueError("Six-team playoffs require at least three playoff weeks")
            wild_scores = weekly_scores.get(weeks[-3], {})
            w36 = self._winner(qualifiers[2], qualifiers[5], wild_scores, seed_order)
            w45 = self._winner(qualifiers[3], qualifiers[4], wild_scores, seed_order)
            survivors = sorted((w36, w45), key=lambda manager: seed_order[manager])
            semifinal_scores = weekly_scores.get(weeks[-2], {})
            low_seed = max(survivors, key=lambda manager: seed_order[manager])
            high_seed = min(survivors, key=lambda manager: seed_order[manager])
            first = self._winner(qualifiers[0], low_seed, semifinal_scores, seed_order)
            second = self._winner(qualifiers[1], high_seed, semifinal_scores, seed_order)
            return self._winner(first, second, weekly_scores.get(weeks[-1], {}), seed_order)
        if len(qualifiers) == 8:
            if len(weeks) < 3:
                raise ValueError("Eight-team playoffs require at least three playoff weeks")
            quarter_scores = weekly_scores.get(weeks[-3], {})
            quarter_pairs = ((0, 7), (1, 6), (2, 5), (3, 4))
            quarter_winners = [
                self._winner(qualifiers[a], qualifiers[b], quarter_scores, seed_order)
                for a, b in quarter_pairs
            ]
            quarter_winners.sort(key=lambda manager: seed_order[manager])
            semi_scores = weekly_scores.get(weeks[-2], {})
            first = self._winner(quarter_winners[0], quarter_winners[-1], semi_scores, seed_order)
            second = self._winner(quarter_winners[1], quarter_winners[-2], semi_scores, seed_order)
            return self._winner(first, second, weekly_scores.get(weeks[-1], {}), seed_order)
        raise ValueError(f"Unsupported playoff field: {len(qualifiers)}")

    def simulate(
        self,
        weekly_draws: pd.DataFrame,
        rosters: pd.DataFrame,
        schedule: pd.DataFrame,
    ) -> pd.DataFrame:
        required_draws = {"simulation", "week", "player_id", "position", "fantasy_points"}
        required_rosters = {"manager_id", "player_id"}
        required_schedule = {"week", "home_manager_id", "away_manager_id"}
        if missing := required_draws - set(weekly_draws):
            raise ValueError(f"Weekly draws missing columns: {sorted(missing)}")
        if missing := required_rosters - set(rosters):
            raise ValueError(f"Rosters missing columns: {sorted(missing)}")
        if missing := required_schedule - set(schedule):
            raise ValueError(f"Schedule missing columns: {sorted(missing)}")

        managers = sorted(rosters["manager_id"].astype(str).unique())
        simulations = sorted(pd.to_numeric(weekly_draws["simulation"], errors="coerce").dropna().astype(int).unique())
        all_weeks = sorted(pd.to_numeric(weekly_draws["week"], errors="coerce").dropna().astype(int).unique())
        regular_weeks = [week for week in all_weeks if week not in set(self.config.playoff_weeks)]
        playoff_count = self._resolved_playoff_teams(len(managers))

        accumulator = {
            manager: {"wins": 0.0, "points": 0.0, "playoffs": 0.0, "championships": 0.0, "seed": 0.0}
            for manager in managers
        }
        for simulation in simulations:
            week_scores = {
                week: self._weekly_scores(weekly_draws, rosters, simulation, week)
                for week in all_weeks
            }
            wins = {manager: 0.0 for manager in managers}
            points = {manager: 0.0 for manager in managers}
            for week in regular_weeks:
                scores = week_scores.get(week, {})
                for manager in managers:
                    points[manager] += scores.get(manager, 0.0)
                week_schedule = schedule.loc[pd.to_numeric(schedule["week"], errors="coerce").eq(week)]
                for _, matchup in week_schedule.iterrows():
                    home = str(matchup["home_manager_id"])
                    away = str(matchup["away_manager_id"])
                    if home not in wins or away not in wins:
                        continue
                    home_score = scores.get(home, 0.0)
                    away_score = scores.get(away, 0.0)
                    if home_score > away_score:
                        wins[home] += 1.0
                    elif away_score > home_score:
                        wins[away] += 1.0
                    else:
                        wins[home] += 0.5
                        wins[away] += 0.5
                if self.config.median_scoring and scores:
                    median = float(np.median([scores.get(manager, 0.0) for manager in managers]))
                    for manager in managers:
                        score = scores.get(manager, 0.0)
                        if score > median:
                            wins[manager] += self.config.median_game_weight
                        elif score == median:
                            wins[manager] += 0.5 * self.config.median_game_weight

            ranking = self._rank(managers, wins, points)
            qualifiers = ranking[:playoff_count]
            champion = self._playoff_champion(qualifiers, week_scores)
            seed_map = {manager: index + 1 for index, manager in enumerate(ranking)}
            for manager in managers:
                accumulator[manager]["wins"] += wins[manager]
                accumulator[manager]["points"] += points[manager]
                accumulator[manager]["playoffs"] += float(manager in qualifiers)
                accumulator[manager]["championships"] += float(manager == champion)
                accumulator[manager]["seed"] += seed_map[manager]

        denominator = max(len(simulations), 1)
        summaries = [
            asdict(
                SeasonSimulationSummary(
                    manager_id=manager,
                    expected_wins=values["wins"] / denominator,
                    expected_points=values["points"] / denominator,
                    playoff_probability=values["playoffs"] / denominator,
                    championship_probability=values["championships"] / denominator,
                    expected_seed=values["seed"] / denominator,
                )
            )
            for manager, values in accumulator.items()
        ]
        return (
            pd.DataFrame(summaries)
            .sort_values("championship_probability", ascending=False, kind="mergesort")
            .reset_index(drop=True)
        )

    def transaction_delta(
        self,
        weekly_draws: pd.DataFrame,
        before_rosters: pd.DataFrame,
        after_rosters: pd.DataFrame,
        schedule: pd.DataFrame,
        *,
        manager_ids: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        before = self.simulate(weekly_draws, before_rosters, schedule).set_index("manager_id")
        after = self.simulate(weekly_draws, after_rosters, schedule).set_index("manager_id")
        managers = list(manager_ids) if manager_ids is not None else sorted(set(before.index) | set(after.index))
        rows: list[dict[str, float | str]] = []
        for manager in managers:
            if manager not in before.index or manager not in after.index:
                continue
            rows.append(
                {
                    "manager_id": str(manager),
                    "expected_wins_delta": float(after.loc[manager, "expected_wins"] - before.loc[manager, "expected_wins"]),
                    "expected_points_delta": float(after.loc[manager, "expected_points"] - before.loc[manager, "expected_points"]),
                    "playoff_probability_delta": float(after.loc[manager, "playoff_probability"] - before.loc[manager, "playoff_probability"]),
                    "championship_probability_delta": float(after.loc[manager, "championship_probability"] - before.loc[manager, "championship_probability"]),
                    "expected_seed_delta": float(after.loc[manager, "expected_seed"] - before.loc[manager, "expected_seed"]),
                }
            )
        return pd.DataFrame(rows)
