from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from player_state_engine.state_graph.regime import RegimeDetector
from player_state_engine.state_graph.role import ROLE_METRICS, DiscountedBetaRoleEstimator
from player_state_engine.state_graph.types import (
    AvailabilityState,
    BetaPosterior,
    ExecutionState,
    PlayerLatentState,
    TeamVolumeState,
)


def _series(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


@dataclass(slots=True)
class PlayerStateGraphBuilder:
    """Build deployable latent player states from point-in-time weekly evidence."""

    role_estimator: DiscountedBetaRoleEstimator = field(default_factory=DiscountedBetaRoleEstimator)
    regime_detector: RegimeDetector = field(default_factory=RegimeDetector)
    efficiency_prior_strength: float = 30.0
    rate_prior_strength: float = 20.0
    recent_weeks: int = 10

    @staticmethod
    def _cutoff(history: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
        data = history.copy()
        data["season"] = pd.to_numeric(data["season"], errors="coerce")
        data["week"] = pd.to_numeric(data["week"], errors="coerce")
        valid = data["season"].lt(int(season)) | (
            data["season"].eq(int(season)) & data["week"].lt(int(week))
        )
        return data.loc[valid].sort_values(["season", "week"], kind="mergesort")

    @staticmethod
    def _beta_from_counts(
        successes: float,
        trials: float,
        *,
        prior_mean: float,
        prior_strength: float,
    ) -> BetaPosterior:
        prior_mean = float(np.clip(prior_mean, 0.001, 0.999))
        strength = max(float(prior_strength), 2.0)
        alpha0 = prior_mean * strength
        beta0 = (1.0 - prior_mean) * strength
        successes = max(float(successes), 0.0)
        trials = max(float(trials), successes)
        return BetaPosterior(
            alpha0 + successes,
            beta0 + trials - successes,
            alpha0,
            beta0,
        )

    @staticmethod
    def _weighted_mean(values: pd.Series, *, fallback: float, half_life: float = 4.0) -> float:
        numeric = pd.to_numeric(values, errors="coerce").dropna()
        if numeric.empty:
            return float(fallback)
        ages = np.arange(len(numeric) - 1, -1, -1, dtype=float)
        weights = np.power(0.5, ages / max(float(half_life), 0.5))
        return float(np.average(numeric.to_numpy(dtype=float), weights=weights))

    @staticmethod
    def _weighted_std(values: pd.Series, *, fallback: float) -> float:
        numeric = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
        if len(numeric) < 2:
            return float(fallback)
        return float(max(np.std(numeric, ddof=1), 0.1))

    def _ensure_role_columns(self, history: pd.DataFrame) -> pd.DataFrame:
        data = history.copy()
        for column in ROLE_METRICS:
            if column not in data:
                data[column] = np.nan
        return data

    def _team_volume(
        self,
        history: pd.DataFrame,
        *,
        team: str,
        position_pool: pd.DataFrame,
    ) -> TeamVolumeState:
        team_rows = history.loc[history["team"].astype(str).eq(str(team))].copy()
        unique_columns = [column for column in ("season", "week", "team", "team_plays", "team_dropbacks", "team_red_zone_trips") if column in team_rows]
        if unique_columns:
            team_rows = team_rows.drop_duplicates([column for column in ("season", "week", "team") if column in team_rows], keep="last")
        team_rows = team_rows.tail(self.recent_weeks)
        plays = _series(team_rows, "team_plays", 64.0)
        dropbacks = _series(team_rows, "team_dropbacks", 37.0)
        plays_mean = self._weighted_mean(plays, fallback=64.0)
        plays_std = self._weighted_std(plays, fallback=6.0)
        total_plays = float(plays.clip(lower=0).sum())
        total_dropbacks = float(dropbacks.clip(lower=0).sum())
        if total_plays > 0:
            observed_rate = total_dropbacks / total_plays
        else:
            observed_rate = 0.58
        dropback_rate = self._beta_from_counts(
            total_dropbacks,
            total_plays,
            prior_mean=float(np.clip(observed_rate, 0.35, 0.75)),
            prior_strength=20.0,
        )
        red_zone = _series(team_rows, "team_red_zone_trips", 3.2)
        return TeamVolumeState(
            plays_mean=plays_mean,
            plays_std=plays_std,
            dropback_rate=dropback_rate,
            red_zone_trips_mean=self._weighted_mean(red_zone, fallback=3.2),
            red_zone_trips_std=self._weighted_std(red_zone, fallback=1.4),
        )

    def _execution(
        self,
        history: pd.DataFrame,
        *,
        player_id: str,
        position: str,
    ) -> ExecutionState:
        player = history.loc[history["player_id"].astype(str).eq(str(player_id))].tail(self.recent_weeks)
        pool = history.loc[history["position"].astype(str).str.upper().eq(position.upper())].tail(500)

        targets = float(_series(player, "targets").sum())
        receptions = float(_series(player, "receptions").sum())
        pool_targets = float(_series(pool, "targets").sum())
        pool_receptions = float(_series(pool, "receptions").sum())
        catch_prior = pool_receptions / pool_targets if pool_targets > 0 else 0.65
        catch_rate = self._beta_from_counts(
            receptions,
            targets,
            prior_mean=catch_prior,
            prior_strength=self.rate_prior_strength,
        )

        pass_attempts = float(_series(player, "pass_attempts").sum())
        passing_tds = float(_series(player, "passing_tds").sum())
        interceptions = float(_series(player, "interceptions").sum())
        pool_attempts = float(_series(pool, "pass_attempts").sum())
        pool_pass_tds = float(_series(pool, "passing_tds").sum())
        pool_ints = float(_series(pool, "interceptions").sum())
        passing_td_rate = self._beta_from_counts(
            passing_tds,
            pass_attempts,
            prior_mean=pool_pass_tds / pool_attempts if pool_attempts > 0 else 0.045,
            prior_strength=self.rate_prior_strength,
        )
        interception_rate = self._beta_from_counts(
            interceptions,
            pass_attempts,
            prior_mean=pool_ints / pool_attempts if pool_attempts > 0 else 0.025,
            prior_strength=self.rate_prior_strength,
        )

        carries = float(_series(player, "carries").sum())
        rushing_tds = float(_series(player, "rushing_tds").sum())
        receiving_tds = float(_series(player, "receiving_tds").sum())
        pool_carries = float(_series(pool, "carries").sum())
        pool_rush_tds = float(_series(pool, "rushing_tds").sum())
        pool_rec_tds = float(_series(pool, "receiving_tds").sum())
        rushing_td_rate = self._beta_from_counts(
            rushing_tds,
            carries,
            prior_mean=pool_rush_tds / pool_carries if pool_carries > 0 else 0.035,
            prior_strength=self.rate_prior_strength,
        )
        receiving_td_rate = self._beta_from_counts(
            receiving_tds,
            targets,
            prior_mean=pool_rec_tds / pool_targets if pool_targets > 0 else 0.055,
            prior_strength=self.rate_prior_strength,
        )

        player_ypt = _series(player, "receiving_yards") / _series(player, "targets").replace(0.0, np.nan)
        pool_ypt = _series(pool, "receiving_yards") / _series(pool, "targets").replace(0.0, np.nan)
        player_ypc = _series(player, "rushing_yards") / _series(player, "carries").replace(0.0, np.nan)
        pool_ypc = _series(pool, "rushing_yards") / _series(pool, "carries").replace(0.0, np.nan)
        player_ypa = _series(player, "passing_yards") / _series(player, "pass_attempts").replace(0.0, np.nan)
        pool_ypa = _series(pool, "passing_yards") / _series(pool, "pass_attempts").replace(0.0, np.nan)

        ypt_prior = float(pool_ypt.replace([np.inf, -np.inf], np.nan).mean()) if pool_ypt.notna().any() else 7.5
        ypc_prior = float(pool_ypc.replace([np.inf, -np.inf], np.nan).mean()) if pool_ypc.notna().any() else 4.2
        ypa_prior = float(pool_ypa.replace([np.inf, -np.inf], np.nan).mean()) if pool_ypa.notna().any() else 7.0

        scramble_attempts = float(_series(player, "scramble_attempts").sum())
        dropbacks = float(_series(player, "dropbacks").sum())
        scramble_rate = self._beta_from_counts(
            scramble_attempts,
            dropbacks,
            prior_mean=0.08 if position.upper() == "QB" else 0.01,
            prior_strength=20.0,
        )

        return ExecutionState(
            catch_rate=catch_rate,
            yards_per_target_mean=self._weighted_mean(player_ypt, fallback=ypt_prior),
            yards_per_target_std=self._weighted_std(player_ypt, fallback=3.0),
            yards_per_carry_mean=self._weighted_mean(player_ypc, fallback=ypc_prior),
            yards_per_carry_std=self._weighted_std(player_ypc, fallback=1.6),
            pass_yards_per_attempt_mean=self._weighted_mean(player_ypa, fallback=ypa_prior),
            pass_yards_per_attempt_std=self._weighted_std(player_ypa, fallback=1.5),
            receiving_td_per_target=receiving_td_rate,
            rushing_td_per_carry=rushing_td_rate,
            passing_td_per_attempt=passing_td_rate,
            interception_per_attempt=interception_rate,
            scramble_rate=scramble_rate,
        )

    def build(
        self,
        weekly_history: pd.DataFrame,
        *,
        player_id: str,
        season: int,
        week: int,
        opponent: str,
        player_name: str | None = None,
        regime_events: pd.DataFrame | None = None,
        environment: dict[str, float] | None = None,
        evidence_cutoff: str | None = None,
    ) -> PlayerLatentState:
        required = {"player_id", "season", "week", "team", "position"}
        missing = required - set(weekly_history)
        if missing:
            raise ValueError(f"Weekly history missing columns: {sorted(missing)}")
        history = self._cutoff(self._ensure_role_columns(weekly_history), season, week)
        player = history.loc[history["player_id"].astype(str).eq(str(player_id))]
        if player.empty:
            raise ValueError(f"No point-in-time history for player {player_id}")
        latest = player.iloc[-1]
        team = str(latest["team"])
        position = str(latest["position"]).upper()
        name = str(player_name or latest.get("player_name") or player_id)

        role = self.role_estimator.estimate_player(
            history,
            player_id=str(player_id),
            season=int(season),
            week=int(week),
        )
        active_series = _series(player.tail(self.recent_weeks), "active", 1.0).clip(0.0, 1.0)
        availability = AvailabilityState(
            active=self._beta_from_counts(
                float(active_series.sum()),
                float(len(active_series)),
                prior_mean=0.94,
                prior_strength=16.0,
            ),
            source_family="objective_availability",
        )
        position_pool = history.loc[history["position"].astype(str).str.upper().eq(position)]
        volume = self._team_volume(history, team=team, position_pool=position_pool)
        execution = self._execution(history, player_id=str(player_id), position=position)
        regime = self.regime_detector.detect(
            regime_events if regime_events is not None else pd.DataFrame(),
            team=team,
            season=int(season),
            week=int(week),
        )
        return PlayerLatentState(
            player_id=str(player_id),
            player_name=name,
            team=team,
            opponent=str(opponent),
            position=position,
            season=int(season),
            week=int(week),
            availability=availability,
            role=role,
            team_volume=volume,
            execution=execution,
            regime=regime,
            environment=dict(environment or {}),
            evidence_cutoff=evidence_cutoff,
        )
