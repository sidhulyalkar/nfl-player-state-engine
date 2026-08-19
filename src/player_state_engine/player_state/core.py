from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from math import exp, log
from typing import Mapping

import numpy as np
from scipy.stats import beta as beta_distribution

ROLE_METRICS = (
    "snap_share",
    "route_participation",
    "target_share",
    "carry_share",
    "red_zone_share",
    "goal_line_share",
    "third_down_share",
    "two_minute_share",
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bounded(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return float(min(high, max(low, value)))


@dataclass(frozen=True, slots=True)
class TemporalEvidenceRecord:
    """Evidence with publication-time semantics for leakage-safe replay.

    ``event_time`` says when the football event happened. ``available_for_prediction_at``
    is the governing timestamp for feature eligibility. Those concepts are intentionally
    separate because a retrospectively published dataset can describe an old game while
    still being unavailable to a live pregame model.
    """

    source_family: str
    event_time: datetime
    published_at: datetime
    first_observed_at: datetime
    retrieved_at: datetime
    available_for_prediction_at: datetime
    coverage: float | None = None
    license: str | None = None
    entity_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "event_time",
            "published_at",
            "first_observed_at",
            "retrieved_at",
            "available_for_prediction_at",
        ):
            object.__setattr__(self, name, _utc(getattr(self, name)))
        if self.coverage is not None and not 0.0 <= float(self.coverage) <= 1.0:
            raise ValueError("coverage must be between 0 and 1")
        if self.first_observed_at < self.published_at:
            raise ValueError("first_observed_at cannot precede published_at")
        if self.retrieved_at < self.first_observed_at:
            raise ValueError("retrieved_at cannot precede first_observed_at")
        if self.available_for_prediction_at < self.published_at:
            raise ValueError("available_for_prediction_at cannot precede published_at")

    def is_available(self, prediction_cutoff: datetime) -> bool:
        return self.available_for_prediction_at <= _utc(prediction_cutoff)


def point_in_time_evidence(
    records: list[TemporalEvidenceRecord], prediction_cutoff: datetime
) -> list[TemporalEvidenceRecord]:
    """Return only records legitimately available at a prediction cutoff."""

    cutoff = _utc(prediction_cutoff)
    return [record for record in records if record.available_for_prediction_at <= cutoff]


@dataclass(frozen=True, slots=True)
class ShareObservation:
    """One point-in-time observation used to update a latent role share."""

    observed_at: datetime
    available_for_prediction_at: datetime
    shares: Mapping[str, float]
    opportunities: Mapping[str, float] = field(default_factory=dict)
    source_family: str = "objective_participation"

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _utc(self.observed_at))
        object.__setattr__(self, "available_for_prediction_at", _utc(self.available_for_prediction_at))
        unknown = set(self.shares) - set(ROLE_METRICS)
        if unknown:
            raise ValueError(f"Unknown role metrics: {sorted(unknown)}")
        for metric, share in self.shares.items():
            if not 0.0 <= float(share) <= 1.0:
                raise ValueError(f"{metric} share must be between 0 and 1")
        for metric, value in self.opportunities.items():
            if metric not in ROLE_METRICS:
                raise ValueError(f"Unknown opportunity metric: {metric}")
            if float(value) < 0.0:
                raise ValueError("opportunity counts must be nonnegative")


@dataclass(frozen=True, slots=True)
class StateEstimate:
    mean: float
    q10: float
    q50: float
    q90: float
    effective_sample_size: float
    maturity: float
    change_probability: float


@dataclass(frozen=True, slots=True)
class RolePosterior:
    player_id: str
    position: str
    as_of: datetime
    states: Mapping[str, StateEstimate]
    role_change_probability: float
    maturity: float
    role_label: str
    evidence_rows: int

    def mean(self, metric: str, default: float = 0.0) -> float:
        state = self.states.get(metric)
        return float(state.mean if state is not None else default)


@dataclass(slots=True)
class _BetaState:
    alpha: float
    beta: float
    prior_alpha: float
    prior_beta: float
    last_observed_at: datetime | None = None
    change_probability: float = 0.0

    @property
    def mean(self) -> float:
        return self.alpha / max(self.alpha + self.beta, 1e-12)

    @property
    def effective_sample_size(self) -> float:
        return self.alpha + self.beta


_DEFAULT_ROLE_PRIORS: dict[str, dict[str, float]] = {
    "QB": {
        "snap_share": 0.95,
        "route_participation": 0.02,
        "target_share": 0.01,
        "carry_share": 0.18,
        "red_zone_share": 0.12,
        "goal_line_share": 0.08,
        "third_down_share": 0.95,
        "two_minute_share": 0.95,
    },
    "RB": {
        "snap_share": 0.55,
        "route_participation": 0.45,
        "target_share": 0.12,
        "carry_share": 0.50,
        "red_zone_share": 0.45,
        "goal_line_share": 0.45,
        "third_down_share": 0.45,
        "two_minute_share": 0.45,
    },
    "WR": {
        "snap_share": 0.75,
        "route_participation": 0.76,
        "target_share": 0.20,
        "carry_share": 0.02,
        "red_zone_share": 0.20,
        "goal_line_share": 0.08,
        "third_down_share": 0.75,
        "two_minute_share": 0.75,
    },
    "TE": {
        "snap_share": 0.70,
        "route_participation": 0.62,
        "target_share": 0.16,
        "carry_share": 0.01,
        "red_zone_share": 0.18,
        "goal_line_share": 0.10,
        "third_down_share": 0.65,
        "two_minute_share": 0.65,
    },
}


class DynamicRoleFilter:
    """Exponentially discounted hierarchical Beta filter for player role shares.

    The filter is deliberately estimator-light. Its job is to provide a transparent latent
    state that reacts faster than rolling averages while retaining position priors when the
    current regime is immature. Every update is gated by ``available_for_prediction_at``.
    """

    def __init__(
        self,
        player_id: str,
        position: str,
        *,
        prior_strength: float = 12.0,
        half_life_weeks: float = 4.0,
        maturity_rows: float = 40.0,
        priors: Mapping[str, float] | None = None,
    ) -> None:
        if prior_strength <= 0 or half_life_weeks <= 0 or maturity_rows <= 0:
            raise ValueError("prior_strength, half_life_weeks, and maturity_rows must be positive")
        self.player_id = str(player_id)
        self.position = str(position).upper()
        self.prior_strength = float(prior_strength)
        self.half_life_weeks = float(half_life_weeks)
        self.maturity_rows = float(maturity_rows)
        base = dict(_DEFAULT_ROLE_PRIORS.get(self.position, _DEFAULT_ROLE_PRIORS["WR"]))
        if priors:
            base.update({key: _bounded(float(value), 1e-4, 1.0 - 1e-4) for key, value in priors.items()})
        self._states: dict[str, _BetaState] = {}
        for metric in ROLE_METRICS:
            mean = _bounded(float(base.get(metric, 0.10)), 1e-4, 1.0 - 1e-4)
            alpha = mean * self.prior_strength
            beta = (1.0 - mean) * self.prior_strength
            self._states[metric] = _BetaState(alpha, beta, alpha, beta)
        self._evidence_rows = 0

    def _decay(self, state: _BetaState, observed_at: datetime) -> None:
        if state.last_observed_at is None:
            return
        elapsed_days = max(0.0, (_utc(observed_at) - state.last_observed_at).total_seconds() / 86400.0)
        factor = 0.5 ** (elapsed_days / (7.0 * self.half_life_weeks))
        state.alpha = state.prior_alpha + factor * (state.alpha - state.prior_alpha)
        state.beta = state.prior_beta + factor * (state.beta - state.prior_beta)

    @staticmethod
    def _surprise_probability(state: _BetaState, share: float, opportunities: float) -> float:
        mean = state.mean
        beta_variance = (
            state.alpha
            * state.beta
            / max((state.alpha + state.beta) ** 2 * (state.alpha + state.beta + 1.0), 1e-12)
        )
        sampling_variance = max(mean * (1.0 - mean) / max(opportunities, 1.0), 1e-6)
        z = abs(float(share) - mean) / np.sqrt(beta_variance + sampling_variance)
        return _bounded(1.0 / (1.0 + exp(-1.6 * (z - 2.0))))

    def update(self, observation: ShareObservation, *, prediction_cutoff: datetime) -> bool:
        if observation.available_for_prediction_at > _utc(prediction_cutoff):
            return False
        for metric, share_value in observation.shares.items():
            state = self._states[metric]
            self._decay(state, observation.observed_at)
            opportunities = max(float(observation.opportunities.get(metric, 1.0)), 1.0)
            share = _bounded(float(share_value), 1e-6, 1.0 - 1e-6)
            surprise = self._surprise_probability(state, share, opportunities)
            state.alpha += share * opportunities
            state.beta += (1.0 - share) * opportunities
            state.change_probability = max(0.65 * state.change_probability, surprise)
            state.last_observed_at = observation.observed_at
        self._evidence_rows += 1
        return True

    def fit(self, observations: list[ShareObservation], *, prediction_cutoff: datetime) -> DynamicRoleFilter:
        for observation in sorted(observations, key=lambda item: (item.available_for_prediction_at, item.observed_at)):
            self.update(observation, prediction_cutoff=prediction_cutoff)
        return self

    def posterior(self, *, as_of: datetime) -> RolePosterior:
        estimates: dict[str, StateEstimate] = {}
        change = 0.0
        maturity_values: list[float] = []
        for metric, state in self._states.items():
            total = state.effective_sample_size
            learned_rows = max(total - self.prior_strength, 0.0)
            maturity = _bounded(learned_rows / self.maturity_rows)
            estimates[metric] = StateEstimate(
                mean=float(state.mean),
                q10=float(beta_distribution.ppf(0.10, state.alpha, state.beta)),
                q50=float(beta_distribution.ppf(0.50, state.alpha, state.beta)),
                q90=float(beta_distribution.ppf(0.90, state.alpha, state.beta)),
                effective_sample_size=float(total),
                maturity=maturity,
                change_probability=float(state.change_probability),
            )
            change = max(change, state.change_probability)
            maturity_values.append(maturity)
        maturity = float(np.mean(maturity_values)) if maturity_values else 0.0
        return RolePosterior(
            player_id=self.player_id,
            position=self.position,
            as_of=_utc(as_of),
            states=estimates,
            role_change_probability=float(change),
            maturity=maturity,
            role_label=self._role_label(estimates),
            evidence_rows=self._evidence_rows,
        )

    def _role_label(self, states: Mapping[str, StateEstimate]) -> str:
        snap = states["snap_share"].mean
        target = states["target_share"].mean
        carry = states["carry_share"].mean
        if self.position == "QB":
            return "starting_qb" if snap >= 0.75 else "rotation_or_backup_qb"
        if self.position == "RB":
            if carry >= 0.58 and snap >= 0.58:
                return "lead_back"
            if states["third_down_share"].mean >= 0.55 and carry < 0.40:
                return "receiving_back"
            return "committee_back"
        if self.position in {"WR", "TE"}:
            if target >= 0.23:
                return "primary_receiver"
            if snap >= 0.70:
                return "full_time_secondary_receiver"
            return "rotational_receiver"
        return "unknown_role"


class RegimeEventType(StrEnum):
    QB_STARTER = "qb_starter_change"
    PLAY_CALLER = "play_caller_change"
    HEAD_COACH = "head_coach_change"
    OFFENSIVE_LINE = "major_ol_change"
    TEAM = "team_change"
    ROOKIE_TRANSITION = "rookie_transition"
    ROLE_INJURY = "major_role_injury"
    SCHEME = "scheme_change"
    SEASON = "season_boundary"


@dataclass(frozen=True, slots=True)
class RegimeEvent:
    event_type: RegimeEventType
    occurred_at: datetime
    available_for_prediction_at: datetime
    weight: float = 1.0
    description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        object.__setattr__(self, "available_for_prediction_at", _utc(self.available_for_prediction_at))
        if not 0.0 < float(self.weight) <= 1.0:
            raise ValueError("regime event weight must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class RegimeState:
    as_of: datetime
    boundary_at: datetime | None
    active_events: tuple[RegimeEventType, ...]
    maturity: float
    current_regime_weight: float
    prior_weight: float
    evidence_events: int


class RegimeTracker:
    """Tracks discontinuities and supplies a maturity-based shrinkage weight."""

    def __init__(self, *, maturity_weeks: float = 5.0) -> None:
        if maturity_weeks <= 0:
            raise ValueError("maturity_weeks must be positive")
        self.maturity_weeks = float(maturity_weeks)

    def estimate(self, events: list[RegimeEvent], *, as_of: datetime) -> RegimeState:
        cutoff = _utc(as_of)
        valid = [event for event in events if event.available_for_prediction_at <= cutoff]
        if not valid:
            return RegimeState(cutoff, None, (), 1.0, 1.0, 0.0, 0)
        valid.sort(key=lambda event: event.occurred_at)
        boundary = valid[-1].occurred_at
        recent = [event for event in valid if event.occurred_at >= boundary]
        elapsed_weeks = max(0.0, (cutoff - boundary).total_seconds() / (86400.0 * 7.0))
        time_maturity = 1.0 - exp(-elapsed_weeks / self.maturity_weeks)
        evidence_maturity = 1.0 - exp(-sum(float(event.weight) for event in recent) / 3.0)
        maturity = _bounded(0.75 * time_maturity + 0.25 * evidence_maturity)
        return RegimeState(
            as_of=cutoff,
            boundary_at=boundary,
            active_events=tuple(dict.fromkeys(event.event_type for event in recent)),
            maturity=maturity,
            current_regime_weight=maturity,
            prior_weight=1.0 - maturity,
            evidence_events=len(recent),
        )

    @staticmethod
    def shrink(current_value: float, historical_prior: float, state: RegimeState) -> float:
        return float(
            state.current_regime_weight * float(current_value)
            + state.prior_weight * float(historical_prior)
        )


def maturity_bucket(value: float) -> str:
    value = _bounded(float(value))
    if value < 0.33:
        return "low"
    if value < 0.67:
        return "medium"
    return "high"
