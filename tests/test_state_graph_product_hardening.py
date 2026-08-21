from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.state_graph.coherent import PlayerStateGraphSampler
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


def _metric(name: str, mean: float, strength: float = 80.0) -> RoleMetricState:
    bounded = float(np.clip(mean, 0.001, 0.999))
    return RoleMetricState(
        name=name,
        posterior=BetaPosterior(bounded * strength, (1.0 - bounded) * strength),
        change_probability=0.05,
        latest_value=bounded,
        observations=8,
    )


def _role(player_id: str, position: str, *, target: float, carry: float) -> DynamicRoleState:
    return DynamicRoleState(
        player_id=player_id,
        team="NE",
        position=position,
        season=2026,
        week=1,
        snap_share=_metric("snap_share", 0.95 if position == "QB" else 0.82),
        route_participation=_metric("route_participation", 0.01 if position == "QB" else 0.80),
        target_share=_metric("target_share", target),
        carry_share=_metric("carry_share", carry),
        red_zone_share=_metric("red_zone_share", 0.20),
        goal_line_share=_metric("goal_line_share", 0.10),
        third_down_share=_metric("third_down_share", 0.70),
        two_minute_share=_metric("two_minute_share", 0.70),
        state_maturity="HIGH",
        aggregate_change_probability=0.05,
        evidence_weeks=8,
    )


def _state(
    player_id: str,
    position: str,
    *,
    target: float = 0.20,
    carry: float = 0.10,
    catch: float = 0.60,
) -> PlayerLatentState:
    return PlayerLatentState(
        player_id=player_id,
        player_name=player_id,
        team="NE",
        opponent="NYJ",
        position=position,
        season=2026,
        week=1,
        availability=AvailabilityState(BetaPosterior(500.0, 1.0)),
        role=_role(player_id, position, target=target, carry=carry),
        team_volume=TeamVolumeState(64.0, 2.0, BetaPosterior(60.0, 40.0)),
        execution=ExecutionState(
            catch_rate=BetaPosterior(catch * 100.0, (1.0 - catch) * 100.0),
            yards_per_target_mean=8.0,
            yards_per_target_std=1.0,
            pass_yards_per_attempt_mean=7.2,
            pass_yards_per_attempt_std=0.8,
            receiving_td_per_target=BetaPosterior(45.0, 55.0),
            passing_td_per_attempt=BetaPosterior(15.0, 85.0),
            interception_per_attempt=BetaPosterior(15.0, 85.0),
        ),
    )


def test_receiver_draws_require_receptions_for_yards_and_touchdowns() -> None:
    sampler = PlayerStateGraphSampler()
    draws = sampler.sample_player(
        _state("WR1", "WR", catch=0.20),
        simulations=2500,
        seed=22,
    )
    assert (draws["receptions"] <= draws["targets"]).all()
    assert (draws["receiving_tds"] <= draws["receptions"]).all()
    assert (draws.loc[draws["receptions"].eq(0), "receiving_yards"] == 0.0).all()


def test_qb_draws_keep_touchdowns_and_interceptions_inside_pass_outcomes() -> None:
    sampler = PlayerStateGraphSampler()
    draws = sampler.sample_player(
        _state("QB1", "QB", target=0.001, carry=0.08, catch=0.40),
        simulations=2500,
        seed=33,
    )
    incompletions = draws["pass_attempts"] - draws["completions"]
    assert (draws["passing_tds"] <= draws["completions"]).all()
    assert (draws["interceptions"] <= incompletions).all()
    assert (draws.loc[draws["completions"].eq(0), "passing_yards"] == 0.0).all()


def test_joint_team_sampler_keeps_unmodeled_opportunity_as_residual() -> None:
    sampler = PlayerStateGraphSampler()
    draws = sampler.sample_team(
        [
            _state("WR1", "WR", target=0.18, carry=0.04),
            _state("WR2", "WR", target=0.16, carry=0.03),
            _state("QB1", "QB", target=0.001, carry=0.08),
        ],
        simulations=800,
        seed=44,
    )
    skill = draws.loc[draws["position"].ne("QB")]
    carry_totals = skill.groupby("simulation")["carries"].sum()
    team_rushes = skill.groupby("simulation")["team_rushes"].first()
    assert (carry_totals <= team_rushes).all()
    assert (carry_totals < team_rushes).mean() > 0.90
    for _, group in draws.groupby("simulation"):
        assert group["team_plays"].nunique() == 1


def test_season_simulator_uses_pregame_lineup_instead_of_hindsight_best_ball() -> None:
    config = LeagueConfig(
        teams=2,
        roster_slots={"QB": 1, "BENCH": 1},
        playoff_weeks=(2,),
    )
    simulator = FantasySeasonSimulator(config=config, playoff_teams=2)
    rosters = pd.DataFrame(
        [
            {"manager_id": "A", "player_id": "A_high_variance", "position": "QB"},
            {"manager_id": "A", "player_id": "A_safe", "position": "QB"},
            {"manager_id": "B", "player_id": "B_qb", "position": "QB"},
        ]
    )
    schedule = pd.DataFrame(
        [{"week": 1, "home_manager_id": "A", "away_manager_id": "B"}]
    )
    rows: list[dict[str, object]] = []
    week_one = {
        0: {"A_high_variance": 100.0, "A_safe": 49.0, "B_qb": 10.0},
        1: {"A_high_variance": 0.0, "A_safe": 49.0, "B_qb": 10.0},
    }
    for simulation, values in week_one.items():
        for player_id, points in values.items():
            rows.append(
                {
                    "simulation": simulation,
                    "week": 1,
                    "player_id": player_id,
                    "position": "QB",
                    "fantasy_points": points,
                }
            )
        for player_id, points in {
            "A_high_variance": 20.0,
            "A_safe": 19.0,
            "B_qb": 10.0,
        }.items():
            rows.append(
                {
                    "simulation": simulation,
                    "week": 2,
                    "player_id": player_id,
                    "position": "QB",
                    "fantasy_points": points,
                }
            )

    result = simulator.simulate(pd.DataFrame(rows), rosters, schedule)
    manager_a = result.loc[result["manager_id"].eq("A")].iloc[0]
    assert manager_a["expected_points"] == pytest.approx(50.0)
    # An oracle that chose the best realized QB separately in each world would score 74.5.
    assert manager_a["expected_points"] < 74.5
