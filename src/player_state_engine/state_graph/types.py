from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np


def _clamp01(value: float) -> float:
    return float(min(1.0, max(0.0, value)))


@dataclass(slots=True, frozen=True)
class BetaPosterior:
    """Compact posterior for a probability-like football state."""

    alpha: float
    beta: float
    prior_alpha: float = 1.0
    prior_beta: float = 1.0

    def __post_init__(self) -> None:
        if self.alpha <= 0 or self.beta <= 0:
            raise ValueError("Beta posterior parameters must be positive")

    @property
    def mean(self) -> float:
        return float(self.alpha / (self.alpha + self.beta))

    @property
    def variance(self) -> float:
        total = self.alpha + self.beta
        return float((self.alpha * self.beta) / (total * total * (total + 1.0)))

    @property
    def std(self) -> float:
        return float(np.sqrt(max(self.variance, 0.0)))

    @property
    def effective_n(self) -> float:
        return float(
            max(
                0.0,
                self.alpha + self.beta - self.prior_alpha - self.prior_beta,
            )
        )

    def quantile(self, probability: float, *, draws: int = 20000, seed: int = 0) -> float:
        if not 0.0 <= probability <= 1.0:
            raise ValueError("probability must be in [0, 1]")
        rng = np.random.default_rng(seed)
        return float(np.quantile(rng.beta(self.alpha, self.beta, size=draws), probability))

    def sample(self, rng: np.random.Generator, size: int | tuple[int, ...] | None = None) -> Any:
        return rng.beta(self.alpha, self.beta, size=size)


@dataclass(slots=True, frozen=True)
class RoleMetricState:
    name: str
    posterior: BetaPosterior
    change_probability: float
    latest_value: float | None = None
    previous_mean: float | None = None
    trend: float = 0.0
    observations: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_probability", _clamp01(self.change_probability))

    @property
    def mean(self) -> float:
        return self.posterior.mean

    @property
    def std(self) -> float:
        return self.posterior.std


@dataclass(slots=True, frozen=True)
class DynamicRoleState:
    player_id: str
    team: str
    position: str
    season: int
    week: int
    snap_share: RoleMetricState
    route_participation: RoleMetricState
    target_share: RoleMetricState
    carry_share: RoleMetricState
    red_zone_share: RoleMetricState
    goal_line_share: RoleMetricState
    third_down_share: RoleMetricState
    two_minute_share: RoleMetricState
    state_maturity: str
    aggregate_change_probability: float
    evidence_weeks: int
    model_source: str = "discounted_beta_dynamic_role_v1"

    def metric(self, name: str) -> RoleMetricState:
        try:
            value = getattr(self, name)
        except AttributeError as exc:
            raise KeyError(name) from exc
        if not isinstance(value, RoleMetricState):
            raise KeyError(name)
        return value

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "snap_share",
            "route_participation",
            "target_share",
            "carry_share",
            "red_zone_share",
            "goal_line_share",
            "third_down_share",
            "two_minute_share",
        ):
            metric = self.metric(key)
            payload[f"{key}_mean"] = metric.mean
            payload[f"{key}_std"] = metric.std
            payload[f"{key}_change_probability"] = metric.change_probability
        return payload


@dataclass(slots=True, frozen=True)
class RegimeState:
    team: str
    season: int
    week: int
    regime_id: str
    weeks_since_boundary: int
    evidence_weight: float
    maturity: str
    active_boundaries: tuple[str, ...] = ()
    prior_weight: float = 1.0
    current_regime_weight: float = 0.0
    model_source: str = "explicit_regime_maturity_v1"


@dataclass(slots=True, frozen=True)
class AvailabilityState:
    active: BetaPosterior
    limited: BetaPosterior | None = None
    evidence_freshness_minutes: float | None = None
    source_family: str = "objective_availability"


@dataclass(slots=True, frozen=True)
class TeamVolumeState:
    plays_mean: float
    plays_std: float
    dropback_rate: BetaPosterior
    red_zone_trips_mean: float = 3.2
    red_zone_trips_std: float = 1.4


@dataclass(slots=True, frozen=True)
class ExecutionState:
    catch_rate: BetaPosterior
    yards_per_target_mean: float = 7.5
    yards_per_target_std: float = 3.0
    yards_per_carry_mean: float = 4.2
    yards_per_carry_std: float = 1.6
    pass_yards_per_attempt_mean: float = 7.0
    pass_yards_per_attempt_std: float = 1.5
    receiving_td_per_target: BetaPosterior = field(default_factory=lambda: BetaPosterior(1.2, 18.0))
    rushing_td_per_carry: BetaPosterior = field(default_factory=lambda: BetaPosterior(1.2, 28.0))
    passing_td_per_attempt: BetaPosterior = field(default_factory=lambda: BetaPosterior(2.0, 38.0))
    interception_per_attempt: BetaPosterior = field(default_factory=lambda: BetaPosterior(1.5, 48.0))
    scramble_rate: BetaPosterior = field(default_factory=lambda: BetaPosterior(2.0, 18.0))


@dataclass(slots=True, frozen=True)
class PlayerLatentState:
    player_id: str
    player_name: str
    team: str
    opponent: str
    position: str
    season: int
    week: int
    availability: AvailabilityState
    role: DynamicRoleState
    team_volume: TeamVolumeState
    execution: ExecutionState
    regime: RegimeState | None = None
    environment: dict[str, float] = field(default_factory=dict)
    evidence_cutoff: str | None = None


@dataclass(slots=True, frozen=True)
class ForecastQuantiles:
    q10: float
    q50: float
    q90: float
    mean: float | None = None
    source: str = "unknown"

    def __post_init__(self) -> None:
        if not self.q10 <= self.q50 <= self.q90:
            raise ValueError("Forecast quantiles must be monotone")


@dataclass(slots=True, frozen=True)
class UncertaintyBreakdown:
    total_variance: float
    components: dict[str, float]

    @property
    def shares(self) -> dict[str, float]:
        denominator = max(float(self.total_variance), 1e-12)
        raw = {key: max(0.0, float(value)) / denominator for key, value in self.components.items()}
        total = sum(raw.values())
        if total <= 0:
            return {key: 0.0 for key in raw}
        return {key: value / total for key, value in raw.items()}
