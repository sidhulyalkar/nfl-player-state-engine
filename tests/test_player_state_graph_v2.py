from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.state_graph.calibration import RecencyWeightedConditionalConformal
from player_state_engine.state_graph.coherent import PlayerStateGraphSampler
from player_state_engine.state_graph.evidence import LatentEvidenceRouter
from player_state_engine.state_graph.experiments import (
    EvidenceTier,
    ExperimentRecord,
    PromotionPolicy,
    paired_block_bootstrap,
)
from player_state_engine.state_graph.fusion import HierarchicalForecastFusion
from player_state_engine.state_graph.provenance import (
    SourceAvailabilityRecord,
    validate_no_future_evidence,
)
from player_state_engine.state_graph.role import DiscountedBetaRoleEstimator
from player_state_engine.state_graph.season_sim import FantasySeasonSimulator
from player_state_engine.state_graph.types import (
    AvailabilityState,
    BetaPosterior,
    DynamicRoleState,
    ExecutionState,
    PlayerLatentState,
    RoleMetricState,
    TeamVolumeState,
)


def _role_history(values: list[float]) -> pd.DataFrame:
    rows = []
    for week, value in enumerate(values, start=1):
        rows.append(
            {
                "player_id": "p1",
                "season": 2026,
                "week": week,
                "team": "SF",
                "position": "WR",
                "snap_share": value,
                "route_participation": value,
                "target_share": value * 0.3,
                "carry_share": 0.01,
                "red_zone_share": value * 0.2,
                "goal_line_share": 0.01,
                "third_down_share": value,
                "two_minute_share": value,
            }
        )
    return pd.DataFrame(rows)


def _metric(name: str, mean: float, strength: float = 60.0) -> RoleMetricState:
    alpha = max(mean, 0.001) * strength
    beta = max(1.0 - mean, 0.001) * strength
    return RoleMetricState(name, BetaPosterior(alpha, beta), 0.1, latest_value=mean, observations=6)


def _role_state() -> DynamicRoleState:
    return DynamicRoleState(
        player_id="p1",
        team="SF",
        position="WR",
        season=2026,
        week=5,
        snap_share=_metric("snap_share", 0.85),
        route_participation=_metric("route_participation", 0.86),
        target_share=_metric("target_share", 0.24),
        carry_share=_metric("carry_share", 0.02),
        red_zone_share=_metric("red_zone_share", 0.28),
        goal_line_share=_metric("goal_line_share", 0.02),
        third_down_share=_metric("third_down_share", 0.78),
        two_minute_share=_metric("two_minute_share", 0.80),
        state_maturity="MEDIUM",
        aggregate_change_probability=0.25,
        evidence_weeks=5,
    )


def test_dynamic_role_state_detects_discontinuous_change() -> None:
    estimator = DiscountedBetaRoleEstimator(half_life_weeks=2.0)
    changed = estimator.estimate_player(
        _role_history([0.25, 0.29, 0.31, 0.71, 0.76]),
        player_id="p1",
        season=2026,
        week=6,
    )
    stable = estimator.estimate_player(
        _role_history([0.25, 0.27, 0.28, 0.29, 0.30]),
        player_id="p1",
        season=2026,
        week=6,
    )
    assert changed.snap_share.mean > stable.snap_share.mean
    assert changed.snap_share.change_probability > stable.snap_share.change_probability
    assert changed.evidence_weeks == 5


def test_publication_time_guard_blocks_retrospective_leakage() -> None:
    cutoff = datetime(2026, 9, 13, 16, 0, tzinfo=UTC)
    safe = SourceAvailabilityRecord(
        source_family="official_injury",
        event_time=cutoff - timedelta(days=1),
        published_at=cutoff - timedelta(hours=2),
        first_observed_at=cutoff - timedelta(hours=2),
        retrieved_at=cutoff - timedelta(hours=1),
        available_for_prediction_at=cutoff - timedelta(hours=2),
    )
    future = SourceAvailabilityRecord(
        source_family="participation_archive",
        event_time=cutoff - timedelta(days=7),
        published_at=cutoff + timedelta(days=100),
        first_observed_at=cutoff + timedelta(days=100),
        retrieved_at=cutoff + timedelta(days=100),
        available_for_prediction_at=cutoff + timedelta(days=100),
    )
    validate_no_future_evidence([safe], prediction_cutoff=cutoff)
    with pytest.raises(ValueError, match="participation_archive"):
        validate_no_future_evidence([safe, future], prediction_cutoff=cutoff)


def test_evidence_router_forbids_personality_feature_dump() -> None:
    router = LatentEvidenceRouter()
    claims = pd.DataFrame(
        [
            {
                "source_family": "player_personality",
                "latent_target": "opportunity",
                "signal_name": "confidence",
                "value": 0.8,
                "confidence": 0.6,
                "available_for_prediction_at": "2026-09-13T12:00:00Z",
            }
        ]
    )
    with pytest.raises(ValueError, match="cannot update"):
        router.route(claims)


def test_coherent_sampler_preserves_stat_constraints_and_exact_scoring() -> None:
    state = PlayerLatentState(
        player_id="p1",
        player_name="Receiver",
        team="SF",
        opponent="SEA",
        position="WR",
        season=2026,
        week=5,
        availability=AvailabilityState(BetaPosterior(200.0, 1.0)),
        role=_role_state(),
        team_volume=TeamVolumeState(64.0, 5.0, BetaPosterior(60.0, 40.0)),
        execution=ExecutionState(
            catch_rate=BetaPosterior(70.0, 30.0),
            yards_per_target_mean=8.2,
            yards_per_target_std=2.0,
        ),
    )
    sampler = PlayerStateGraphSampler()
    draws = sampler.sample_player(state, simulations=600, seed=11)
    assert (draws["receptions"] <= draws["targets"]).all()
    assert (draws["targets"] <= draws["routes"]).all()
    assert (draws.loc[draws["targets"].eq(0), "receiving_yards"] == 0).all()
    scored = sampler.score_draws(draws, LeagueConfig(scoring="ppr"))
    assert "league_fantasy_points" in scored
    assert np.isfinite(scored["league_fantasy_points"]).all()


def test_conditional_conformal_widens_undercovered_intervals() -> None:
    rows = []
    for index in range(80):
        actual = float(index % 10)
        rows.append(
            {
                "season": 2025,
                "week": index % 18 + 1,
                "position": "QB",
                "target": "passing_yards",
                "actual": actual,
                "q10": actual + 2.0,
                "q50": actual + 3.0,
                "q90": actual + 4.0,
            }
        )
    calibrator = RecencyWeightedConditionalConformal(min_cell_rows=20).fit(pd.DataFrame(rows))
    forecast = pd.DataFrame(
        [{"position": "QB", "target": "passing_yards", "q10": 10.0, "q50": 12.0, "q90": 14.0}]
    )
    calibrated = calibrator.transform(forecast).iloc[0]
    assert calibrated["q10_calibrated"] < 10.0
    assert calibrated["q90_calibrated"] >= 14.0
    assert calibrated["calibration_level"] == "position_target"


def test_fusion_learns_to_prefer_better_archived_expert() -> None:
    rows = []
    rng = np.random.default_rng(3)
    for _index in range(100):
        actual = float(rng.normal(15.0, 4.0))
        for expert, bias in (("direct", 0.2), ("world", 1.5), ("consensus", 4.5)):
            median = actual + bias
            rows.append(
                {
                    "expert": expert,
                    "actual": actual,
                    "q10": median - 5.0,
                    "q50": median,
                    "q90": median + 5.0,
                    "position": "WR",
                    "target": "fantasy_points",
                    "horizon": "sunday",
                    "regime_maturity": "HIGH",
                }
            )
    fusion = HierarchicalForecastFusion(min_rows=20).fit(pd.DataFrame(rows))
    weights, _ = fusion.weights_for(
        position="WR",
        target="fantasy_points",
        horizon="sunday",
        regime_maturity="HIGH",
    )
    assert weights["direct"] > weights["world"] > weights["consensus"]


def test_paired_block_bootstrap_and_fail_closed_promotion_gate() -> None:
    frame = pd.DataFrame(
        {
            "season": [2024] * 4 + [2025] * 4,
            "week": [1, 2, 3, 4] * 2,
            "champion": [1.0] * 8,
            "challenger": [0.8] * 8,
        }
    )
    effect = paired_block_bootstrap(
        frame,
        champion_column="champion",
        challenger_column="challenger",
        bootstrap_samples=300,
    )
    assert effect.effect > 0
    record = ExperimentRecord(
        experiment_id="psg-test",
        challenger="graph",
        champion="direct",
        primary_metric="pinball",
        evidence_tier=EvidenceTier.SINGLE_HISTORICAL_SLICE,
        effect=effect.effect,
        ci_low=effect.ci_low,
        ci_high=effect.ci_high,
        season_consistency=1.0,
        position_consistency=1.0,
        week_consistency=1.0,
        coverage=1.0,
        data_availability=1.0,
        negative_control_passed=True,
    )
    evaluated = PromotionPolicy().evaluate(record)
    assert not evaluated.promoted
    assert any("evidence_tier" in blocker for blocker in evaluated.blockers)


def test_rest_of_season_simulator_outputs_decision_probabilities() -> None:
    config = LeagueConfig(
        teams=4,
        roster_slots={"QB": 1, "BENCH": 0},
        playoff_weeks=(3,),
        median_scoring=True,
    )
    simulator = FantasySeasonSimulator(config=config, playoff_teams=2)
    rosters = pd.DataFrame(
        [
            {"manager_id": manager, "player_id": f"{manager}_qb", "position": "QB"}
            for manager in ("A", "B", "C", "D")
        ]
    )
    schedule = pd.DataFrame(
        [
            {"week": 1, "home_manager_id": "A", "away_manager_id": "D"},
            {"week": 1, "home_manager_id": "B", "away_manager_id": "C"},
            {"week": 2, "home_manager_id": "A", "away_manager_id": "C"},
            {"week": 2, "home_manager_id": "B", "away_manager_id": "D"},
        ]
    )
    rows = []
    base = {"A": 30.0, "B": 25.0, "C": 15.0, "D": 10.0}
    for simulation in range(3):
        for week in (1, 2, 3):
            for manager, points in base.items():
                rows.append(
                    {
                        "simulation": simulation,
                        "week": week,
                        "player_id": f"{manager}_qb",
                        "position": "QB",
                        "fantasy_points": points + simulation * 0.1,
                    }
                )
    result = simulator.simulate(pd.DataFrame(rows), rosters, schedule)
    a = result.loc[result["manager_id"].eq("A")].iloc[0]
    assert a["playoff_probability"] == pytest.approx(1.0)
    assert a["championship_probability"] == pytest.approx(1.0)
