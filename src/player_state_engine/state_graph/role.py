from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.state_graph.types import BetaPosterior, DynamicRoleState, RoleMetricState

ROLE_METRICS: tuple[str, ...] = (
    "snap_share",
    "route_participation",
    "target_share",
    "carry_share",
    "red_zone_share",
    "goal_line_share",
    "third_down_share",
    "two_minute_share",
)


@dataclass(slots=True)
class DiscountedBetaRoleEstimator:
    """Point-in-time role filter with explicit discontinuity detection.

    Each share is represented as a discounted Beta posterior. Recent observations can move the
    state quickly while sparse roles shrink toward a position prior. Change probability is a
    bounded evidence score, not a causal probability: it combines standardized deviation from
    the pre-update state with recent slope consistency.
    """

    half_life_weeks: float = 3.0
    prior_strength: float = 8.0
    change_z_threshold: float = 1.5
    slope_scale: float = 0.12
    min_history: int = 2

    def _discount(self, age_weeks: np.ndarray) -> np.ndarray:
        half_life = max(float(self.half_life_weeks), 0.25)
        return np.power(0.5, np.asarray(age_weeks, dtype=float) / half_life)

    @staticmethod
    def _maturity(effective_n: float, weeks: int) -> str:
        if weeks < 3 or effective_n < 8:
            return "LOW"
        if weeks < 6 or effective_n < 20:
            return "MEDIUM"
        return "HIGH"

    def _metric_prior(self, values: pd.Series, position_values: pd.Series | None) -> tuple[float, float]:
        pool = position_values if position_values is not None else values
        numeric = pd.to_numeric(pool, errors="coerce").dropna().clip(0.001, 0.999)
        prior_mean = float(numeric.mean()) if not numeric.empty else 0.5
        strength = max(float(self.prior_strength), 2.0)
        return prior_mean * strength, (1.0 - prior_mean) * strength

    def _estimate_metric(
        self,
        frame: pd.DataFrame,
        metric: str,
        *,
        position_prior_values: pd.Series | None = None,
    ) -> RoleMetricState:
        if metric not in frame:
            values = pd.Series(dtype=float)
        else:
            values = pd.to_numeric(frame[metric], errors="coerce").dropna().clip(0.0, 1.0)
        if values.empty:
            alpha0, beta0 = self._metric_prior(pd.Series(dtype=float), position_prior_values)
            posterior = BetaPosterior(alpha0, beta0, alpha0, beta0)
            return RoleMetricState(metric, posterior, 0.0, observations=0)

        alpha0, beta0 = self._metric_prior(values, position_prior_values)
        ages = np.arange(len(values) - 1, -1, -1, dtype=float)
        weights = self._discount(ages)
        successes = float(np.sum(weights * values.to_numpy(dtype=float)))
        failures = float(np.sum(weights * (1.0 - values.to_numpy(dtype=float))))
        posterior = BetaPosterior(alpha0 + successes, beta0 + failures, alpha0, beta0)

        previous_mean: float | None = None
        z_score = 0.0
        if len(values) >= self.min_history:
            previous = values.iloc[:-1]
            prev_ages = np.arange(len(previous) - 1, -1, -1, dtype=float)
            prev_weights = self._discount(prev_ages)
            prev_success = float(np.sum(prev_weights * previous.to_numpy(dtype=float)))
            prev_failure = float(np.sum(prev_weights * (1.0 - previous.to_numpy(dtype=float))))
            previous_posterior = BetaPosterior(
                alpha0 + prev_success,
                beta0 + prev_failure,
                alpha0,
                beta0,
            )
            previous_mean = previous_posterior.mean
            denominator = max(previous_posterior.std, 0.025)
            z_score = abs(float(values.iloc[-1]) - previous_mean) / denominator

        trend = 0.0
        recent = values.tail(3).to_numpy(dtype=float)
        if len(recent) >= 2:
            trend = float(np.polyfit(np.arange(len(recent), dtype=float), recent, deg=1)[0])
        deviation_signal = 1.0 / (1.0 + np.exp(-(z_score - self.change_z_threshold)))
        slope_signal = 1.0 - np.exp(-abs(trend) / max(self.slope_scale, 1e-6))
        change_probability = float(np.clip(0.72 * deviation_signal + 0.28 * slope_signal, 0.0, 1.0))
        if len(values) < self.min_history:
            change_probability *= 0.35

        return RoleMetricState(
            name=metric,
            posterior=posterior,
            change_probability=change_probability,
            latest_value=float(values.iloc[-1]),
            previous_mean=previous_mean,
            trend=trend,
            observations=int(len(values)),
        )

    def estimate_player(
        self,
        history: pd.DataFrame,
        *,
        player_id: str,
        season: int,
        week: int,
    ) -> DynamicRoleState:
        required = {"player_id", "season", "week", "team", "position"}
        missing = required - set(history)
        if missing:
            raise ValueError(f"Role history missing columns: {sorted(missing)}")

        chronology = history.copy()
        chronology["season"] = pd.to_numeric(chronology["season"], errors="coerce")
        chronology["week"] = pd.to_numeric(chronology["week"], errors="coerce")
        cutoff = chronology["season"].lt(int(season)) | (
            chronology["season"].eq(int(season)) & chronology["week"].lt(int(week))
        )
        chronology = chronology.loc[cutoff].sort_values(["season", "week"], kind="mergesort")
        player = chronology.loc[chronology["player_id"].astype(str).eq(str(player_id))].copy()
        if player.empty:
            raise ValueError(f"No point-in-time role history for player {player_id}")

        latest = player.iloc[-1]
        position = str(latest["position"]).upper()
        team = str(latest["team"])
        position_pool = chronology.loc[chronology["position"].astype(str).str.upper().eq(position)]

        metrics: dict[str, RoleMetricState] = {}
        for metric in ROLE_METRICS:
            position_values = position_pool[metric] if metric in position_pool else None
            metrics[metric] = self._estimate_metric(
                player,
                metric,
                position_prior_values=position_values,
            )

        aggregate_change = float(
            1.0 - np.prod([1.0 - state.change_probability for state in metrics.values()])
        )
        effective_n = float(np.mean([state.posterior.effective_n for state in metrics.values()]))
        weeks = int(player[["season", "week"]].drop_duplicates().shape[0])
        maturity = self._maturity(effective_n, weeks)

        return DynamicRoleState(
            player_id=str(player_id),
            team=team,
            position=position,
            season=int(season),
            week=int(week),
            snap_share=metrics["snap_share"],
            route_participation=metrics["route_participation"],
            target_share=metrics["target_share"],
            carry_share=metrics["carry_share"],
            red_zone_share=metrics["red_zone_share"],
            goal_line_share=metrics["goal_line_share"],
            third_down_share=metrics["third_down_share"],
            two_minute_share=metrics["two_minute_share"],
            state_maturity=maturity,
            aggregate_change_probability=aggregate_change,
            evidence_weeks=weeks,
        )

    def transform(
        self,
        history: pd.DataFrame,
        forecast_rows: pd.DataFrame,
    ) -> pd.DataFrame:
        required = {"player_id", "season", "week"}
        missing = required - set(forecast_rows)
        if missing:
            raise ValueError(f"Forecast rows missing columns: {sorted(missing)}")
        records: list[dict[str, object]] = []
        for _, row in forecast_rows.iterrows():
            state = self.estimate_player(
                history,
                player_id=str(row["player_id"]),
                season=int(row["season"]),
                week=int(row["week"]),
            )
            records.append(state.to_dict())
        return pd.DataFrame(records)
