from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.decision import (
    DriveTerminationHazardModel,
    FourthDownDecisionModel,
)
from player_state_engine.game_intelligence.decision_simulator import (
    simulate_matchup_decision_probe,
)
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.schema import SimulationConfig
from player_state_engine.game_intelligence.terminal import (
    TERMINAL_FAMILIES,
    TerminalFamilyModel,
    attach_terminal_family_labels,
    evaluate_terminal_family_scores,
    extract_terminal_family_events,
    permute_conditional_terminal_families_within_context_season,
    permute_terminal_families_within_context_season,
)
from player_state_engine.game_intelligence.terminal_benchmark import (
    recommend_v017_development,
    run_v016_terminal_benchmark,
    v016_terminal_promotion_gate,
)
from player_state_engine.game_intelligence.terminal_simulator import (
    simulate_matchup_terminal_probe,
)
from tests.test_game_intelligence_v011 import _players
from tests.test_game_intelligence_v014 import (
    _matchup,
    _research_inputs,
    _transition_pbp,
    _transition_schedules,
)


def _semantic_terminal_pbp() -> pd.DataFrame:
    base = {
        "season": 2026,
        "week": 1,
        "game_id": "semantic",
        "home_team": "AAA",
        "away_team": "BBB",
        "score_differential": 0.0,
        "no_play": 0,
        "sack": 0,
        "qb_scramble": 0,
        "fumble_lost": 0,
    }
    rows = [
        {
            **base,
            "play_id": 1,
            "posteam": "AAA",
            "defteam": "BBB",
            "pass_attempt": 1,
            "rush_attempt": 0,
            "qb_dropback": 1,
            "down": 3,
            "ydstogo": 6.0,
            "yardline_100": 55.0,
            "qtr": 2,
            "game_seconds_remaining": 1900.0,
            "yards_gained": 2.0,
            "touchdown": 0,
            "first_down": 0,
            "complete_pass": 1,
            "interception": 0,
            "turnover": 0,
            "play_type": "pass",
            "punt_attempt": 0,
            "field_goal_attempt": 0,
        },
        {
            **base,
            "play_id": 2,
            "posteam": "AAA",
            "defteam": "BBB",
            "pass_attempt": 0,
            "rush_attempt": 0,
            "qb_dropback": 0,
            "down": 4,
            "ydstogo": 4.0,
            "yardline_100": 53.0,
            "qtr": 2,
            "game_seconds_remaining": 1888.0,
            "yards_gained": 0.0,
            "touchdown": 0,
            "first_down": 0,
            "complete_pass": 0,
            "interception": 0,
            "turnover": 0,
            "play_type": "punt",
            "punt_attempt": 1,
            "field_goal_attempt": 0,
        },
        {
            **base,
            "play_id": 3,
            "posteam": "BBB",
            "defteam": "AAA",
            "pass_attempt": 0,
            "rush_attempt": 1,
            "qb_dropback": 0,
            "down": 1,
            "ydstogo": 10.0,
            "yardline_100": 70.0,
            "qtr": 2,
            "game_seconds_remaining": 1820.0,
            "yards_gained": 4.0,
            "touchdown": 0,
            "first_down": 0,
            "complete_pass": 0,
            "interception": 0,
            "turnover": 0,
            "play_type": "run",
            "punt_attempt": 0,
            "field_goal_attempt": 0,
        },
        {
            **base,
            "play_id": 4,
            "posteam": "AAA",
            "defteam": "BBB",
            "pass_attempt": 0,
            "rush_attempt": 1,
            "qb_dropback": 0,
            "down": 4,
            "ydstogo": 2.0,
            "yardline_100": 40.0,
            "qtr": 3,
            "game_seconds_remaining": 1200.0,
            "yards_gained": 0.0,
            "touchdown": 0,
            "first_down": 0,
            "complete_pass": 0,
            "interception": 0,
            "turnover": 0,
            "play_type": "run",
            "punt_attempt": 0,
            "field_goal_attempt": 0,
        },
        {
            **base,
            "play_id": 5,
            "posteam": "BBB",
            "defteam": "AAA",
            "pass_attempt": 1,
            "rush_attempt": 0,
            "qb_dropback": 1,
            "down": 2,
            "ydstogo": 8.0,
            "yardline_100": 35.0,
            "qtr": 4,
            "game_seconds_remaining": 80.0,
            "yards_gained": 0.0,
            "touchdown": 0,
            "first_down": 0,
            "complete_pass": 0,
            "interception": 1,
            "turnover": 1,
            "play_type": "pass",
            "punt_attempt": 0,
            "field_goal_attempt": 0,
        },
    ]
    return pd.DataFrame(rows)


def _terminal_conditioned_inputs():
    (
        raw,
        tendencies,
        usage,
        play_model,
        _,
        opportunity_model,
        drive_model,
        transition_model,
    ) = _research_inputs()
    plays = build_play_intelligence_frame(raw)
    chronology = plays["season"] * 25 + plays["week"]
    raw_chronology = raw["season"] * 25 + raw["week"]
    train_plays = plays.loc[chronology < 2026 * 25 + 2]
    train_raw = raw.loc[raw_chronology < 2026 * 25 + 2]
    labeled = attach_terminal_family_labels(train_plays, train_raw)
    outcome_model = EmpiricalPlayOutcomeModel(min_stratum_plays=2).fit(labeled)
    terminal_model = TerminalFamilyModel(prior_strength=3.0).fit(train_raw)
    decision_model = FourthDownDecisionModel(prior_strength=3.0).fit(train_raw)
    hazard_model = DriveTerminationHazardModel(prior_strength=3.0).fit(train_raw)
    return (
        raw,
        tendencies,
        usage,
        play_model,
        outcome_model,
        opportunity_model,
        drive_model,
        transition_model,
        decision_model,
        terminal_model,
        hazard_model,
    )


def test_terminal_extractor_preserves_fourth_down_policy_boundary() -> None:
    events = extract_terminal_family_events(_semantic_terminal_pbp())
    by_play = events.set_index("play_id")["terminal_family"].to_dict()
    assert by_play[1] == "CONTINUE"
    assert by_play[3] == "END_HALF"
    assert by_play[4] == "DOWNS"
    assert by_play[5] == "TURNOVER"
    assert set(events["terminal_family"]) <= set(TERMINAL_FAMILIES)


def test_terminal_permutations_preserve_registered_controls() -> None:
    events = extract_terminal_family_events(_transition_pbp())
    full = permute_terminal_families_within_context_season(events, seed=17)
    for key, original in events.groupby(["season", "down_bucket", "field_zone"], sort=False):
        challenger = full.loc[
            (full["season"] == key[0])
            & full["down_bucket"].eq(key[1])
            & full["field_zone"].eq(key[2])
        ]
        assert sorted(original["terminal_family"].tolist()) == sorted(
            challenger["terminal_family"].tolist()
        )

    conditional = permute_conditional_terminal_families_within_context_season(
        events, seed=19
    )
    assert conditional["terminated"].tolist() == events["terminated"].tolist()
    assert conditional.loc[events["terminated"].eq(0), "terminal_family"].eq(
        "CONTINUE"
    ).all()


def test_terminal_model_is_point_in_time_normalized_and_structurally_safe() -> None:
    raw = _transition_pbp()
    chronology = raw["season"] * 25 + raw["week"]
    train = raw.loc[chronology < 2026 * 25 + 2]
    test = raw.loc[(raw["season"] == 2026) & (raw["week"] == 2)]
    model = TerminalFamilyModel(prior_strength=3.0).fit(train)
    assert model.train_max_season == 2026
    assert model.train_max_week == 1
    state = {
        "down": 3.0,
        "ydstogo": 7.0,
        "yardline_100": 45.0,
        "game_seconds_remaining": 1300.0,
        "score_differential": 0.0,
    }
    distribution = model.distribution(
        team="AAA", state=state, play_family="DROPBACK", authority_mode=True
    )
    assert set(distribution) == set(TERMINAL_FAMILIES)
    assert np.isclose(sum(distribution.values()), 1.0)
    assert distribution["DOWNS"] == 0.0
    assert distribution["END_HALF"] == 0.0
    metrics = evaluate_terminal_family_scores(model.score_events(test))
    assert np.isfinite(metrics["terminal_family_log_loss"])
    assert np.isfinite(metrics["terminal_family_brier"])
    assert np.isfinite(metrics["canonical_termination_brier"])


def test_empirical_outcome_model_samples_family_compatible_rows() -> None:
    raw = _transition_pbp()
    plays = build_play_intelligence_frame(raw)
    labeled = attach_terminal_family_labels(plays, raw)
    model = EmpiricalPlayOutcomeModel(min_stratum_plays=2).fit(labeled)
    row = labeled.loc[
        (labeled["terminal_family"] == "DOWNS") & (labeled["play_family"] == "RUSH")
    ].iloc[0]
    sampled = model.sample_for_terminal_family(
        play_family=str(row["play_family"]),
        down=int(row["down"]),
        distance_bucket=int(row["distance_bucket"]),
        field_zone=int(row["field_zone"]),
        terminal_family="DOWNS",
        rng=np.random.default_rng(11),
    )
    assert sampled.get("touchdown", 0.0) < 0.5
    assert sampled.get("turnover", 0.0) < 0.5
    assert sampled.get("first_down", 0.0) < 0.5


def test_terminal_off_probe_matches_v015_core_draws() -> None:
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
    decision_model = FourthDownDecisionModel(prior_strength=3.0).fit(train)
    hazard_model = DriveTerminationHazardModel(prior_strength=3.0).fit(train)
    config = SimulationConfig(simulations=3, max_plays=60, seed=41)
    kwargs = {
        "tendencies": tendencies,
        "usage": usage,
        "outcome_model": outcome_model,
        "play_call_model": play_model,
        "opportunity_model": opportunity_model,
        "drive_volume_model": drive_model,
        "transition_model": transition_model,
        "decision_model": decision_model,
        "termination_hazard_model": hazard_model,
        "league_config": LeagueConfig(),
        "config": config,
    }
    frozen = simulate_matchup_decision_probe(_matchup(), **kwargs)
    instrumented = simulate_matchup_terminal_probe(
        _matchup(), terminal_family_model=None, **kwargs
    )
    pd.testing.assert_frame_equal(frozen.game_draws, instrumented.game_draws)
    pd.testing.assert_frame_equal(frozen.player_draws, instrumented.player_draws)
    common = list(frozen.team_draws.columns)
    pd.testing.assert_frame_equal(frozen.team_draws, instrumented.team_draws[common])
    assert instrumented.diagnostics["terminal_family_authority"] is False


def test_terminal_authority_is_deterministic_and_preserves_legacy_rng_consumption() -> None:
    (
        _,
        tendencies,
        usage,
        play_model,
        outcome_model,
        opportunity_model,
        drive_model,
        transition_model,
        decision_model,
        terminal_model,
        _,
    ) = _terminal_conditioned_inputs()
    config = SimulationConfig(simulations=3, max_plays=60, seed=43)
    kwargs = {
        "tendencies": tendencies,
        "usage": usage,
        "outcome_model": outcome_model,
        "play_call_model": play_model,
        "opportunity_model": opportunity_model,
        "drive_volume_model": drive_model,
        "transition_model": transition_model,
        "decision_model": decision_model,
        "terminal_family_model": terminal_model,
        "league_config": LeagueConfig(),
        "config": config,
    }
    first = simulate_matchup_terminal_probe(_matchup(), **kwargs)
    second = simulate_matchup_terminal_probe(_matchup(), **kwargs)
    pd.testing.assert_frame_equal(first.team_draws, second.team_draws)
    pd.testing.assert_frame_equal(first.player_draws, second.player_draws)
    assert {
        "terminal_non_clock_events",
        "terminal_score_events",
        "terminal_turnover_events",
        "terminal_downs_events",
        "terminal_end_half_events",
    } <= set(first.team_draws)
    assert first.diagnostics["terminal_family_authority"] is True
    assert first.diagnostics["terminal_shadow_rng_advances_legacy_stream"] is False
    assert first.diagnostics["aligned_legacy_outcome_draws"] == first.diagnostics[
        "terminal_probability_calls"
    ]
    assert first.diagnostics["production_projection_changed"] is False


def test_v016_benchmark_exposes_eight_cells_and_fails_closed_small_sample() -> None:
    result = run_v016_terminal_benchmark(
        _transition_pbp(),
        _transition_schedules(),
        test_seasons=(2026,),
        week_start=2,
        week_end=2,
        players=_players(),
        league_config=LeagueConfig(),
        simulations_per_game=1,
        max_games_per_week=1,
        seed=23,
        opportunity_prior_strength=4.0,
        drive_prior_strength=4.0,
        transition_prior_strength=2.0,
        decision_prior_strength=2.0,
        terminal_prior_strength=2.0,
    )
    assert len(result.aggregate_metrics) == 8
    assert set(result.aggregate_metrics) == {
        "legacy_transition_legacy_decision_legacy_terminal",
        "legacy_transition_legacy_decision_terminal",
        "legacy_transition_decision_legacy_terminal",
        "legacy_transition_decision_terminal",
        "transition_legacy_decision_legacy_terminal",
        "transition_legacy_decision_terminal",
        "transition_decision_legacy_terminal",
        "transition_decision_terminal",
    }
    assert result.diagnostics["protocol"] == "v016_terminal_family_eight_cell_expanding_weekly"
    assert result.diagnostics["legacy_outcome_rng_alignment"] is True
    assert not result.weekly_isolated_metrics.empty

    decision = v016_terminal_promotion_gate(result)
    assert decision.promoted is False
    assert any("held-out seasons" in reason for reason in decision.reasons)
    recommendation = recommend_v017_development(result)
    assert recommendation["research_only"] is True
    assert recommendation["production_projection_changed"] is False


def test_terminal_model_fails_closed_on_missing_schema() -> None:
    bad = pd.DataFrame({"season": [2026], "week": [1]})
    try:
        extract_terminal_family_events(bad)
    except ValueError as exc:
        assert "game_id" in str(exc)
    else:
        raise AssertionError("terminal extraction should fail closed on missing game identity")
