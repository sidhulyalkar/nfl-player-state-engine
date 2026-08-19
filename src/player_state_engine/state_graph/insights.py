from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

import numpy as np
import pandas as pd

from player_state_engine.state_graph.types import DynamicRoleState, ForecastQuantiles, UncertaintyBreakdown


@dataclass(slots=True, frozen=True)
class ProjectionAttribution:
    previous_median: float
    current_median: float
    changes: dict[str, float]
    residual: float
    label: str = "model attribution, not causal truth"


@dataclass(slots=True, frozen=True)
class ScenarioResult:
    name: str
    quantiles: ForecastQuantiles
    probability_above_baseline: float | None = None


@dataclass(slots=True, frozen=True)
class PlayerIntelligenceCard:
    player_id: str
    player_name: str
    position: str
    median: float
    q10: float
    q90: float
    probability_top12: float | None
    probability_top24: float | None
    probability_bust_below_replacement: float | None
    probability_active: float
    expected_routes: float | None
    expected_targets: float | None
    expected_red_zone_opportunities: float | None
    role_state: str
    role_change_probability: float
    projection_confidence: str
    main_upside_driver: str | None
    main_downside_driver: str | None
    consensus_disagreement: float | None
    evidence_freshness: str | None
    uncertainty_shares: dict[str, float] = field(default_factory=dict)
    model_source: str = "player_intelligence_card_v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def projection_change_attribution(
    previous_median: float,
    current_median: float,
    component_changes: Mapping[str, float],
) -> ProjectionAttribution:
    changes = {str(key): float(value) for key, value in component_changes.items()}
    explained = sum(changes.values())
    residual = float(current_median) - float(previous_median) - explained
    return ProjectionAttribution(
        previous_median=float(previous_median),
        current_median=float(current_median),
        changes=changes,
        residual=float(residual),
    )


def compare_scenarios(
    baseline_draws: np.ndarray,
    scenarios: Mapping[str, np.ndarray],
) -> list[ScenarioResult]:
    baseline = np.asarray(baseline_draws, dtype=float)
    baseline = baseline[np.isfinite(baseline)]
    if len(baseline) < 20:
        raise ValueError("Baseline scenario requires at least 20 draws")
    baseline_median = float(np.median(baseline))
    results: list[ScenarioResult] = []
    for name, values in scenarios.items():
        draws = np.asarray(values, dtype=float)
        draws = draws[np.isfinite(draws)]
        if len(draws) < 20:
            continue
        q10, q50, q90 = np.quantile(draws, [0.10, 0.50, 0.90])
        results.append(
            ScenarioResult(
                name=str(name),
                quantiles=ForecastQuantiles(float(q10), float(q50), float(q90), float(draws.mean()), "scenario"),
                probability_above_baseline=float(np.mean(draws > baseline_median)),
            )
        )
    return results


def upside_path(
    draws: pd.DataFrame,
    *,
    fantasy_column: str = "league_fantasy_points",
    threshold: float = 25.0,
    driver_columns: tuple[str, ...] = (
        "team_dropbacks",
        "targets",
        "red_zone_trips",
        "routes",
        "carries",
    ),
) -> dict[str, dict[str, float]]:
    if fantasy_column not in draws:
        raise ValueError(f"Missing fantasy column: {fantasy_column}")
    fantasy = pd.to_numeric(draws[fantasy_column], errors="coerce")
    high = draws.loc[fantasy.ge(float(threshold))]
    baseline = draws.loc[fantasy.notna()]
    if high.empty:
        return {}
    result: dict[str, dict[str, float]] = {}
    for column in driver_columns:
        if column not in draws:
            continue
        high_values = pd.to_numeric(high[column], errors="coerce").dropna()
        base_values = pd.to_numeric(baseline[column], errors="coerce").dropna()
        if high_values.empty or base_values.empty:
            continue
        result[column] = {
            "upside_median": float(high_values.median()),
            "baseline_median": float(base_values.median()),
            "upside_q25": float(high_values.quantile(0.25)),
            "delta": float(high_values.median() - base_values.median()),
        }
    return result


def build_intelligence_card(
    *,
    player_id: str,
    player_name: str,
    position: str,
    scored_draws: pd.DataFrame,
    role: DynamicRoleState,
    probability_active: float,
    replacement_threshold: float | None = None,
    top12_threshold: float | None = None,
    top24_threshold: float | None = None,
    uncertainty: UncertaintyBreakdown | None = None,
    consensus_median: float | None = None,
    evidence_freshness: str | None = None,
) -> PlayerIntelligenceCard:
    values = pd.to_numeric(scored_draws["league_fantasy_points"], errors="coerce").dropna()
    if len(values) < 20:
        raise ValueError("Intelligence card requires at least 20 scored draws")
    q10, q50, q90 = values.quantile([0.10, 0.50, 0.90]).tolist()

    expected_routes = float(pd.to_numeric(scored_draws["routes"], errors="coerce").mean()) if "routes" in scored_draws else None
    expected_targets = float(pd.to_numeric(scored_draws["targets"], errors="coerce").mean()) if "targets" in scored_draws else None
    if "red_zone_trips" in scored_draws:
        expected_rz = float(
            pd.to_numeric(scored_draws["red_zone_trips"], errors="coerce").mean()
            * role.red_zone_share.mean
        )
    else:
        expected_rz = None

    probability_top12 = float(np.mean(values >= top12_threshold)) if top12_threshold is not None else None
    probability_top24 = float(np.mean(values >= top24_threshold)) if top24_threshold is not None else None
    bust = float(np.mean(values < replacement_threshold)) if replacement_threshold is not None else None
    width = float(q90 - q10)
    maturity_bonus = {"LOW": -1, "MEDIUM": 0, "HIGH": 1}.get(role.state_maturity, 0)
    if width <= 8 and maturity_bonus >= 0:
        confidence = "HIGH"
    elif width <= 15 and maturity_bonus >= -1:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    role_metrics = {
        "target share": role.target_share.trend,
        "carry share": role.carry_share.trend,
        "route participation": role.route_participation.trend,
        "red-zone share": role.red_zone_share.trend,
    }
    upside = max(role_metrics, key=role_metrics.get) if any(value > 0 for value in role_metrics.values()) else None
    downside = min(role_metrics, key=role_metrics.get) if any(value < 0 for value in role_metrics.values()) else None
    role_label = f"{position.upper()} role / {role.state_maturity.lower()} maturity"
    disagreement = float(q50 - consensus_median) if consensus_median is not None else None

    return PlayerIntelligenceCard(
        player_id=str(player_id),
        player_name=str(player_name),
        position=str(position).upper(),
        median=float(q50),
        q10=float(q10),
        q90=float(q90),
        probability_top12=probability_top12,
        probability_top24=probability_top24,
        probability_bust_below_replacement=bust,
        probability_active=float(max(0.0, min(1.0, probability_active))),
        expected_routes=expected_routes,
        expected_targets=expected_targets,
        expected_red_zone_opportunities=expected_rz,
        role_state=role_label,
        role_change_probability=role.aggregate_change_probability,
        projection_confidence=confidence,
        main_upside_driver=upside,
        main_downside_driver=downside,
        consensus_disagreement=disagreement,
        evidence_freshness=evidence_freshness,
        uncertainty_shares=uncertainty.shares if uncertainty is not None else {},
    )
