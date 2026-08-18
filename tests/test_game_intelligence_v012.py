from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.evaluation import evaluate_player_opportunity
from player_state_engine.game_intelligence.factorial import (
    recommend_next_development,
    run_v012_factorial_benchmark,
    v012_state_opportunity_promotion_gate,
)
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.opportunity import (
    StateConditionedOpportunityModel,
    permute_context_within_team_season,
)
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.schema import MatchupSpec, SimulationConfig
from player_state_engine.game_intelligence.simulator import simulate_matchup
from player_state_engine.game_intelligence.tendencies import (
    attach_point_in_time_matchup_features,
    build_team_tendency_snapshots,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles
from tests.test_game_intelligence_v011 import _players, _schedules, _synthetic_pbp


def _research_inputs():
    plays = build_play_intelligence_frame(_synthetic_pbp())
    tendencies = build_team_tendency_snapshots(plays)
    enriched = attach_point_in_time_matchup_features(plays, tendencies)
    chronology = enriched["season"] * 25 + enriched["week"]
    train = enriched.loc[chronology < 2026 * 25 + 2]
    play_model = PlayCallModel().fit(train)
    outcome_model = EmpiricalPlayOutcomeModel(min_stratum_plays=2).fit(train)
    opportunity_model = StateConditionedOpportunityModel(prior_strength=4.0).fit(train)
    usage = build_player_usage_profiles(plays, season=2026, week=2, players=_players())
    return plays, tendencies, usage, play_model, outcome_model, opportunity_model


def test_state_allocator_can_be_restricted_to_current_eligible_players() -> None:
    plays = build_play_intelligence_frame(_synthetic_pbp())
    train = plays.loc[(plays["season"] < 2026) | (plays["week"] < 2)]
    model = StateConditionedOpportunityModel(prior_strength=4.0).fit(train)
    state = plays.loc[plays["posteam"].eq("AAA") & plays["play_family"].eq("DROPBACK")].iloc[0]
    distribution = model.distribution(
        team="AAA",
        opportunity_type="target",
        state=state,
        eligible_player_ids=["AAA_WR1"],
    )
    assert distribution["player_id"].tolist() == ["AAA_WR1"]
    assert distribution["probability"].iloc[0] == 1.0


def test_context_permutation_preserves_team_season_rows_but_breaks_mapping() -> None:
    plays = build_play_intelligence_frame(_synthetic_pbp())
    permuted = permute_context_within_team_season(plays, seed=17)
    original_counts = plays.groupby(["season", "posteam"], sort=False).size()
    permuted_counts = permuted.groupby(["season", "posteam"], sort=False).size()
    pd.testing.assert_series_equal(original_counts, permuted_counts)
    checked = ("red_zone", "distance_bucket", "field_zone")
    for column in checked:
        for key, original_group in plays.groupby(["season", "posteam"], sort=False):
            permuted_group = permuted.loc[
                (permuted["season"] == key[0]) & permuted["posteam"].eq(key[1])
            ]
            assert sorted(original_group[column].astype(str)) == sorted(
                permuted_group[column].astype(str)
            )
    assert any(not permuted[column].equals(plays[column]) for column in checked)


def test_simulator_records_realized_opportunity_and_keeps_game_path_common() -> None:
    _, tendencies, usage, play_model, outcome_model, opportunity_model = _research_inputs()
    unrelated = usage.iloc[[0]].copy()
    unrelated["team"] = "CCC"
    unrelated["player_id"] = "CCC_GHOST"
    usage_with_unrelated = pd.concat([usage, unrelated], ignore_index=True)
    matchup = MatchupSpec(
        season=2026,
        week=2,
        home_team="AAA",
        away_team="BBB",
        game_id="2026_02_BBB_AAA",
        home_spread=-2.5,
        game_total=46.0,
    )
    config = SimulationConfig(simulations=4, max_plays=60, seed=23)
    static = simulate_matchup(
        matchup,
        tendencies=tendencies,
        usage=usage_with_unrelated,
        outcome_model=outcome_model,
        play_call_model=play_model,
        league_config=LeagueConfig(),
        config=config,
    )
    state = simulate_matchup(
        matchup,
        tendencies=tendencies,
        usage=usage_with_unrelated,
        outcome_model=outcome_model,
        play_call_model=play_model,
        opportunity_model=opportunity_model,
        league_config=LeagueConfig(),
        config=config,
    )
    assert {"carries", "targets"} <= set(state.player_draws)
    assert state.player_draws[["carries", "targets"]].to_numpy().sum() > 0
    assert state.diagnostics["opportunity_allocation_model"].endswith("v012")
    assert state.diagnostics["state_allocation_attempts"] > 0
    assert state.diagnostics["complete_player_draw_matrix"] is True
    expected_players = usage.loc[usage["team"].isin(["AAA", "BBB"]), "player_id"].astype(str).nunique()
    expected_rows = config.simulations * expected_players
    assert len(state.player_draws) == expected_rows
    assert state.player_draws.groupby("simulation")["player_id"].nunique().eq(expected_players).all()
    assert "CCC_GHOST" not in set(state.player_draws["player_id"])
    assert set(state.player_draws["team"]) == {"AAA", "BBB"}
    pd.testing.assert_frame_equal(static.team_draws, state.team_draws)


def test_player_opportunity_union_scoring_penalizes_missing_roles() -> None:
    predicted = pd.DataFrame(
        {"game_id": ["g"], "player_id": ["P1"], "carries": [4.0], "targets": [0.0]}
    )
    observed = pd.DataFrame(
        {"game_id": ["g"], "player_id": ["P2"], "carries": [6.0], "targets": [0.0]}
    )
    metrics = evaluate_player_opportunity(predicted, observed)
    assert metrics["player_rows"] == 2.0
    assert metrics["observed_player_coverage"] == 0.0
    assert metrics["player_carries_mae"] == 5.0


def test_zero_role_rows_do_not_dilute_opportunity_error() -> None:
    predicted = pd.DataFrame(
        {
            "game_id": ["g", "g"],
            "player_id": ["P1", "ZERO_QB"],
            "carries": [4.0, 0.0],
            "targets": [0.0, 0.0],
        }
    )
    observed = pd.DataFrame(
        {"game_id": ["g"], "player_id": ["P2"], "carries": [6.0], "targets": [0.0]}
    )
    metrics = evaluate_player_opportunity(predicted, observed)
    assert metrics["player_rows"] == 2.0
    assert metrics["predicted_player_rows"] == 1.0
    assert metrics["player_carries_mae"] == 5.0


def test_factorial_replay_exposes_four_variants_and_fails_closed_on_small_sample() -> None:
    result = run_v012_factorial_benchmark(
        _synthetic_pbp(),
        _schedules(),
        test_seasons=(2026,),
        week_start=2,
        week_end=2,
        players=_players(),
        league_config=LeagueConfig(),
        simulations_per_game=2,
        max_games_per_week=1,
        seed=5,
        opportunity_prior_strength=4.0,
    )
    assert set(result.aggregate_metrics) == {
        "profile_static",
        "learned_static",
        "profile_state",
        "learned_state",
    }
    assert result.diagnostics["protocol"] == "v012_factorial_expanding_weekly_point_in_time"
    assert result.diagnostics["common_random_numbers"] is True
    assert not result.weekly_ablation_metrics.empty
    assert np.isfinite(result.aggregate_ablation_metrics["full__log_loss"])
    assert result.aggregate_metrics["profile_static"]["team_points_mae"] == result.aggregate_metrics[
        "profile_state"
    ]["team_points_mae"]

    decision = v012_state_opportunity_promotion_gate(result)
    assert decision.promoted is False
    assert any("held-out seasons" in reason for reason in decision.reasons)
    recommendation = recommend_next_development(result)
    assert recommendation["research_only"] is True
    assert recommendation["next_experiment"]
