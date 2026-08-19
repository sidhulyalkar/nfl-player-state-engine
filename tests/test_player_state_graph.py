from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.player_state import (
    DynamicRoleFilter,
    EvidenceTier,
    ExecutionState,
    ExperimentEvidence,
    FantasySeasonSimulator,
    HierarchicalForecastFusion,
    PlayerStateGraph,
    PlayerStateSnapshot,
    RecencyWeightedConditionalConformal,
    ShareObservation,
    TeamVolumeState,
    TemporalEvidenceRecord,
    calibration_report,
    paired_block_bootstrap,
    point_in_time_evidence,
    projection_change_attribution,
)


def _time(day: int) -> datetime:
    return datetime(2025, 9, day, 16, tzinfo=UTC)


def _receiver_role(cutoff: datetime):
    observations = [
        ShareObservation(
            observed_at=_time(1),
            available_for_prediction_at=_time(2),
            shares={
                "snap_share": 0.82,
                "route_participation": 0.84,
                "target_share": 0.21,
                "red_zone_share": 0.24,
            },
            opportunities={
                "snap_share": 60,
                "route_participation": 38,
                "target_share": 34,
                "red_zone_share": 8,
            },
        ),
        ShareObservation(
            observed_at=_time(8),
            available_for_prediction_at=_time(9),
            shares={
                "snap_share": 0.91,
                "route_participation": 0.92,
                "target_share": 0.31,
                "red_zone_share": 0.32,
            },
            opportunities={
                "snap_share": 64,
                "route_participation": 41,
                "target_share": 37,
                "red_zone_share": 9,
            },
        ),
    ]
    role_filter = DynamicRoleFilter("wr-1", "WR", prior_strength=10.0, maturity_rows=40.0)
    role_filter.fit(observations, prediction_cutoff=cutoff)
    return role_filter.posterior(as_of=cutoff)


def test_temporal_evidence_uses_availability_timestamp_not_event_time() -> None:
    old_event_late_release = TemporalEvidenceRecord(
        source_family="participation",
        event_time=_time(1),
        published_at=_time(8),
        first_observed_at=_time(8) + timedelta(minutes=5),
        retrieved_at=_time(8) + timedelta(minutes=10),
        available_for_prediction_at=_time(8) + timedelta(minutes=15),
    )
    cutoff = _time(5)
    assert point_in_time_evidence([old_event_late_release], cutoff) == []
    assert point_in_time_evidence([old_event_late_release], _time(9)) == [old_event_late_release]


def test_temporal_evidence_fails_closed_on_impossible_provenance() -> None:
    with pytest.raises(ValueError, match="first_observed_at"):
        TemporalEvidenceRecord(
            source_family="injury",
            event_time=_time(1),
            published_at=_time(4),
            first_observed_at=_time(3),
            retrieved_at=_time(5),
            available_for_prediction_at=_time(5),
        )


def test_dynamic_role_filter_reacts_to_discontinuous_usage_and_ignores_future_rows() -> None:
    role_filter = DynamicRoleFilter("wr-change", "WR", prior_strength=12.0, maturity_rows=50.0)
    steady = ShareObservation(
        observed_at=_time(1),
        available_for_prediction_at=_time(2),
        shares={"target_share": 0.12, "snap_share": 0.55},
        opportunities={"target_share": 45, "snap_share": 65},
    )
    jump = ShareObservation(
        observed_at=_time(8),
        available_for_prediction_at=_time(9),
        shares={"target_share": 0.42, "snap_share": 0.93},
        opportunities={"target_share": 45, "snap_share": 65},
    )
    future = ShareObservation(
        observed_at=_time(10),
        available_for_prediction_at=_time(12),
        shares={"target_share": 0.95},
        opportunities={"target_share": 100},
    )
    role_filter.fit([steady, jump, future], prediction_cutoff=_time(10))
    posterior = role_filter.posterior(as_of=_time(10))
    assert posterior.evidence_rows == 2
    assert 0.20 < posterior.mean("target_share") < 0.42
    assert posterior.role_change_probability > 0.50
    assert posterior.states["target_share"].q10 <= posterior.states["target_share"].q50
    assert posterior.states["target_share"].q50 <= posterior.states["target_share"].q90


def test_player_state_graph_generates_coherent_stats_then_exact_league_points() -> None:
    league = LeagueConfig(teams=12, scoring="ppr")
    role = _receiver_role(_time(10))
    snapshot = PlayerStateSnapshot(
        player_id="wr-1",
        position="WR",
        role=role,
        team_volume=TeamVolumeState(36.0, 4.0, 26.0, 4.0),
        execution=ExecutionState(catch_rate=0.70, yards_per_reception=12.0),
        p_active=1.0,
    )
    graph = PlayerStateGraph(league)
    draws = graph.simulate(snapshot, simulations=600, seed=7)
    assert (draws["receptions"] <= draws["targets"] + 1e-12).all()
    assert (draws["targets"] <= draws["routes"] + 1e-12).all()
    assert (draws["carries"] <= draws["team_rushes"] + 1e-12).all()
    assert np.isfinite(draws["league_fantasy_points"]).all()
    summary = graph.summarize(draws)
    assert summary["q10"] <= summary["q50"] <= summary["q90"]
    manual = (
        draws["receptions"]
        + 0.1 * draws["receiving_yards"]
        + 6.0 * draws["receiving_tds"]
        + 0.1 * draws["rushing_yards"]
        + 6.0 * draws["rushing_tds"]
    )
    assert np.allclose(draws["league_fantasy_points"], manual)


def test_uncertainty_decomposition_is_normalized_and_nonnegative() -> None:
    graph = PlayerStateGraph(LeagueConfig())
    snapshot = PlayerStateSnapshot(
        player_id="wr-1",
        position="WR",
        role=_receiver_role(_time(10)),
        team_volume=TeamVolumeState(36.0, 5.0, 26.0, 4.0),
        execution=ExecutionState(),
        p_active=0.90,
        environment_sd=0.10,
    )
    breakdown = graph.decompose_uncertainty(snapshot, simulations=500, seed=9)
    shares = [
        breakdown.availability,
        breakdown.team_volume,
        breakdown.role_opportunity,
        breakdown.execution,
        breakdown.environment,
        breakdown.residual_model,
    ]
    assert breakdown.total_variance > 0.0
    assert all(value >= 0.0 for value in shares)
    assert sum(shares) == pytest.approx(1.0, abs=1e-6)


def test_recency_weighted_conditional_conformal_expands_undercovered_intervals() -> None:
    actual = np.linspace(-3.0, 3.0, 240)
    history = pd.DataFrame(
        {
            "actual": actual,
            "q10": np.full(len(actual), -0.5),
            "q50": np.zeros(len(actual)),
            "q90": np.full(len(actual), 0.5),
            "position": ["WR"] * len(actual),
            "target": ["fantasy_points"] * len(actual),
            "prediction_timestamp": pd.date_range("2024-01-01", periods=len(actual), freq="D", tz="UTC"),
        }
    )
    before = calibration_report(history)
    calibrator = RecencyWeightedConditionalConformal(min_group_rows=20).fit(history)
    after_frame = calibrator.transform(history.drop(columns=["actual"])).assign(actual=actual)
    after = calibration_report(after_frame)
    assert after["interval_coverage"] > before["interval_coverage"]
    assert after["interval_width"] > before["interval_width"]
    assert (after_frame["q10"] <= after_frame["q50"]).all()
    assert (after_frame["q50"] <= after_frame["q90"]).all()


def test_hierarchical_forecast_fusion_learns_and_exposes_expert_disagreement() -> None:
    actual = np.linspace(5.0, 25.0, 220)
    history = pd.DataFrame(
        {
            "actual": actual,
            "position": ["WR"] * len(actual),
            "target": ["fantasy_points"] * len(actual),
            "forecast_horizon": ["weekly"] * len(actual),
            "regime_maturity_bucket": ["high"] * len(actual),
        }
    )
    for expert, offset in (("direct", 0.1), ("world", 3.5), ("consensus", -2.5)):
        history[f"{expert}_q10"] = actual + offset - 2.0
        history[f"{expert}_q50"] = actual + offset
        history[f"{expert}_q90"] = actual + offset + 2.0
    fusion = HierarchicalForecastFusion(min_group_rows=20, shrinkage_rows=20.0).fit(history)
    output = fusion.transform(history.drop(columns=["actual"]))
    weights = output[["fusion_weight_direct", "fusion_weight_world", "fusion_weight_consensus"]]
    assert np.allclose(weights.sum(axis=1), 1.0)
    assert float(weights["fusion_weight_direct"].mean()) > 0.50
    assert (output["expert_disagreement_range"] > 0).all()
    assert output["fusion_research_only"].eq(1).all()


def _season_draws(simulations: int = 30) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    manager_points = {"A": 24.0, "B": 18.0, "C": 12.0, "D": 6.0}
    for simulation_id in range(simulations):
        for week in range(1, 6):
            for manager, points in manager_points.items():
                rows.append(
                    {
                        "simulation_id": simulation_id,
                        "week": week,
                        "player_id": f"qb-{manager}",
                        "manager_id": manager,
                        "position": "QB",
                        "league_fantasy_points": points,
                    }
                )
    return pd.DataFrame(rows)


def test_fantasy_season_simulator_reaches_playoff_and_championship_probabilities() -> None:
    config = LeagueConfig(
        teams=4,
        roster_slots={"QB": 1},
        playoff_weeks=(4, 5),
        median_scoring=True,
    )
    schedule = pd.DataFrame(
        [
            {"week": 1, "manager_id": "A", "opponent_id": "B"},
            {"week": 1, "manager_id": "C", "opponent_id": "D"},
            {"week": 2, "manager_id": "A", "opponent_id": "C"},
            {"week": 2, "manager_id": "B", "opponent_id": "D"},
            {"week": 3, "manager_id": "A", "opponent_id": "D"},
            {"week": 3, "manager_id": "B", "opponent_id": "C"},
        ]
    )
    result = FantasySeasonSimulator(config, playoff_teams=4).simulate(_season_draws(), schedule)
    a = result.manager_metrics.set_index("manager_id").loc["A"]
    assert a["playoff_probability"] == pytest.approx(1.0)
    assert a["championship_probability"] == pytest.approx(1.0)
    assert result.simulations == 30


def test_block_bootstrap_and_evidence_tier_fail_closed_until_multi_season() -> None:
    frame = pd.DataFrame(
        {
            "season": np.repeat([2023, 2024, 2025], 8),
            "week": list(range(1, 9)) * 3,
            "candidate": np.full(24, 0.80),
            "reference": np.full(24, 1.00),
        }
    )
    effect = paired_block_bootstrap(
        frame,
        candidate_column="candidate",
        reference_column="reference",
        metric="pinball",
        samples=500,
    )
    assert effect.effect == pytest.approx(-0.20)
    assert effect.ci_high < 0.0
    weak = ExperimentEvidence(
        experiment_id="E-test",
        evidence_tier=EvidenceTier.SINGLE_HISTORICAL_SLICE,
        primary_metric="pinball",
        effect=effect,
        season_consistency=1.0,
        position_consistency=1.0,
        coverage=1.0,
        source_availability=1.0,
        negative_control_passed=True,
        downstream_decision_passed=None,
        preregistered=True,
        minimum_useful_effect=0.05,
    )
    assert not weak.promotion_eligible
    strong = ExperimentEvidence(
        **{**weak.__dict__, "evidence_tier": EvidenceTier.MULTI_SEASON_ISOLATED}
    )
    assert strong.promotion_eligible


def test_projection_change_attribution_is_additive_and_not_labeled_causal() -> None:
    attribution = projection_change_attribution(
        12.0,
        16.0,
        {"teammate_out": 2.0, "route_share": 1.0, "team_total": 0.5},
    )
    assert sum(attribution.contributions.values()) == pytest.approx(4.0)
    assert "model" in attribution.method
