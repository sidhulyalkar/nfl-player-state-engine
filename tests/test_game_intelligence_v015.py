from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.decision import (
    DriveTerminationHazardModel,
    FourthDownDecisionModel,
    evaluate_fourth_down_scores,
    evaluate_termination_scores,
    extract_drive_termination_events,
    extract_fourth_down_decisions,
    legacy_fourth_down_probabilities,
    permute_fourth_down_actions_within_context_season,
    permute_termination_targets_within_context_season,
)
from player_state_engine.game_intelligence.decision_benchmark import (
    recommend_v016_development,
    run_v015_decision_benchmark,
    v015_decision_promotion_gate,
)
from player_state_engine.game_intelligence.decision_simulator import (
    simulate_matchup_decision_probe,
)
from player_state_engine.game_intelligence.schema import SimulationConfig
from player_state_engine.game_intelligence.transition_simulator import (
    simulate_matchup_transition_probe,
)
from tests.test_game_intelligence_v011 import _players
from tests.test_game_intelligence_v014 import (
    _matchup,
    _research_inputs,
    _transition_pbp,
    _transition_schedules,
)


def test_fourth_down_extractor_and_legacy_probabilities() -> None:
    raw = _transition_pbp()
    decisions = extract_fourth_down_decisions(raw)
    assert not decisions.empty
    assert {"GO", "PUNT", "FIELD_GOAL"} <= set(decisions["action"])
    assert {"field_zone", "distance_bucket", "clock_bucket", "score_state"} <= set(
        decisions.columns
    )
    probability = legacy_fourth_down_probabilities(yardline_100=30.0, ydstogo=2.0)
    assert set(probability) == {"GO", "PUNT", "FIELD_GOAL"}
    assert np.isclose(sum(probability.values()), 1.0)
    assert probability["FIELD_GOAL"] > 0.0
    assert probability["PUNT"] == 0.0


def test_decision_and_termination_permutations_preserve_broad_marginals() -> None:
    raw = _transition_pbp()
    decisions = extract_fourth_down_decisions(raw)
    shuffled = permute_fourth_down_actions_within_context_season(decisions, seed=17)
    for key, original in decisions.groupby(
        ["season", "field_zone", "distance_bucket"], sort=False
    ):
        challenger = shuffled.loc[
            (shuffled["season"] == key[0])
            & shuffled["field_zone"].eq(key[1])
            & shuffled["distance_bucket"].eq(key[2])
        ]
        assert sorted(original["action"].tolist()) == sorted(challenger["action"].tolist())

    termination = extract_drive_termination_events(raw)
    permuted = permute_termination_targets_within_context_season(termination, seed=17)
    for key, original in termination.groupby(
        ["season", "down_bucket", "field_zone"], sort=False
    ):
        challenger = permuted.loc[
            (permuted["season"] == key[0])
            & permuted["down_bucket"].eq(key[1])
            & permuted["field_zone"].eq(key[2])
        ]
        assert sorted(original["terminated"].tolist()) == sorted(
            challenger["terminated"].tolist()
        )


def test_decision_and_termination_models_are_point_in_time_and_score_finite() -> None:
    raw = _transition_pbp()
    chronology = raw["season"] * 25 + raw["week"]
    train = raw.loc[chronology < 2026 * 25 + 2]
    test = raw.loc[(raw["season"] == 2026) & (raw["week"] == 2)]

    decision = FourthDownDecisionModel(prior_strength=4.0).fit(train)
    termination = DriveTerminationHazardModel(prior_strength=4.0).fit(train)
    assert decision.train_max_season == 2026
    assert decision.train_max_week == 1
    assert termination.train_max_season == 2026
    assert termination.train_max_week == 1

    decision_metrics = evaluate_fourth_down_scores(decision.score_events(test))
    termination_metrics = evaluate_termination_scores(termination.score_events(test))
    assert np.isfinite(decision_metrics["fourth_down_log_loss"])
    assert np.isfinite(decision_metrics["heuristic_fourth_down_log_loss"])
    assert np.isfinite(termination_metrics["termination_log_loss"])
    assert np.isfinite(termination_metrics["team_base_termination_log_loss"])


def test_decision_distribution_is_normalized_and_contextual() -> None:
    raw = _transition_pbp()
    model = FourthDownDecisionModel(prior_strength=2.0).fit(raw)
    state = {
        "down": 4.0,
        "ydstogo": 2.0,
        "yardline_100": 30.0,
        "game_seconds_remaining": 600.0,
        "score_differential": -10.0,
    }
    distribution = model.distribution(team="AAA", state=state)
    assert set(distribution) == {"GO", "PUNT", "FIELD_GOAL"}
    assert np.isclose(sum(distribution.values()), 1.0)
    assert all(0.0 <= value <= 1.0 for value in distribution.values())


def test_decision_off_probe_matches_frozen_v014_core_draws() -> None:
    (
        _,
        tendencies,
        usage,
        play_model,
        outcome_model,
        opportunity_model,
        drive_model,
        transition_model,
    ) = _research_inputs()
    config = SimulationConfig(simulations=3, max_plays=60, seed=31)
    frozen = simulate_matchup_transition_probe(
        _matchup(),
        tendencies=tendencies,
        usage=usage,
        outcome_model=outcome_model,
        play_call_model=play_model,
        opportunity_model=opportunity_model,
        drive_volume_model=drive_model,
        transition_model=transition_model,
        league_config=LeagueConfig(),
        config=config,
    )
    instrumented = simulate_matchup_decision_probe(
        _matchup(),
        tendencies=tendencies,
        usage=usage,
        outcome_model=outcome_model,
        play_call_model=play_model,
        opportunity_model=opportunity_model,
        drive_volume_model=drive_model,
        transition_model=transition_model,
        decision_model=None,
        termination_hazard_model=None,
        league_config=LeagueConfig(),
        config=config,
    )
    pd.testing.assert_frame_equal(frozen.game_draws, instrumented.game_draws)
    pd.testing.assert_frame_equal(frozen.player_draws, instrumented.player_draws)
    common = list(frozen.team_draws.columns)
    pd.testing.assert_frame_equal(frozen.team_draws, instrumented.team_draws[common])


def test_decision_probe_is_deterministic_and_hazard_is_diagnostic_only() -> None:
    (
        raw,
        tendencies,
        usage,
        play_model,
        outcome_model,
        opportunity_model,
        drive_model,
        transition_model,
    ) = _research_inputs()
    chronology = raw["season"] * 25 + raw["week"]
    train = raw.loc[chronology < 2026 * 25 + 2]
    decision = FourthDownDecisionModel(prior_strength=4.0).fit(train)
    termination = DriveTerminationHazardModel(prior_strength=4.0).fit(train)
    config = SimulationConfig(simulations=3, max_plays=60, seed=37)
    kwargs = {
        "tendencies": tendencies,
        "usage": usage,
        "outcome_model": outcome_model,
        "play_call_model": play_model,
        "opportunity_model": opportunity_model,
        "drive_volume_model": drive_model,
        "transition_model": transition_model,
        "decision_model": decision,
        "termination_hazard_model": termination,
        "league_config": LeagueConfig(),
        "config": config,
    }
    first = simulate_matchup_decision_probe(_matchup(), **kwargs)
    second = simulate_matchup_decision_probe(_matchup(), **kwargs)
    pd.testing.assert_frame_equal(first.team_draws, second.team_draws)
    pd.testing.assert_frame_equal(first.player_draws, second.player_draws)
    assert {
        "fourth_down_decisions",
        "fourth_down_go_attempts",
        "punts",
        "field_goal_attempts",
    } <= set(first.team_draws)
    assert first.diagnostics["decision_rng_stream_added"] is True
    assert first.diagnostics["component_rng_base_version"] == 13
    assert first.diagnostics["termination_hazard_authority"] is False
    assert first.diagnostics["fourth_down_decision_model"].endswith("v015")
    assert first.diagnostics["production_projection_changed"] is False


def test_v015_benchmark_exposes_four_cells_and_fails_closed_small_sample() -> None:
    result = run_v015_decision_benchmark(
        _transition_pbp(),
        _transition_schedules(),
        test_seasons=(2026,),
        week_start=2,
        week_end=2,
        players=_players(),
        league_config=LeagueConfig(),
        simulations_per_game=1,
        max_games_per_week=1,
        seed=19,
        opportunity_prior_strength=4.0,
        drive_prior_strength=4.0,
        transition_prior_strength=2.0,
        decision_prior_strength=2.0,
        termination_prior_strength=2.0,
    )
    assert set(result.aggregate_metrics) == {
        "legacy_transition_legacy_decision",
        "legacy_transition_decision",
        "transition_legacy_decision",
        "transition_decision",
    }
    assert result.diagnostics["protocol"] == "v015_fourth_down_decision_four_cell_expanding_weekly"
    assert result.diagnostics["termination_hazard"].startswith("evaluated in isolation")
    assert not result.weekly_isolated_metrics.empty

    decision = v015_decision_promotion_gate(result)
    assert decision.promoted is False
    assert any("held-out seasons" in reason for reason in decision.reasons)
    recommendation = recommend_v016_development(result)
    assert recommendation["research_only"] is True
    assert recommendation["production_projection_changed"] is False


def test_decision_models_fail_closed_on_missing_schema() -> None:
    bad = pd.DataFrame({"season": [2026], "week": [1]})
    try:
        extract_fourth_down_decisions(bad)
    except ValueError as exc:
        assert "game_id" in str(exc)
    else:
        raise AssertionError("decision extraction should fail closed on missing game identity")

    try:
        extract_drive_termination_events(bad)
    except ValueError as exc:
        assert "game_id" in str(exc)
    else:
        raise AssertionError("termination extraction should fail closed on missing game identity")
