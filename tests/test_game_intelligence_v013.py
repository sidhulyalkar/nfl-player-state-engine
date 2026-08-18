from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.drive import (
    DriveVolumeModel,
    evaluate_drive_volume_draws,
    extract_drive_frame,
    observed_drive_volume,
    permute_pace_targets_within_team_season,
)
from player_state_engine.game_intelligence.drive_simulator import (
    simulate_matchup_volume_probe,
)
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.opportunity import StateConditionedOpportunityModel
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.schema import MatchupSpec, SimulationConfig
from player_state_engine.game_intelligence.tendencies import (
    attach_point_in_time_matchup_features,
    build_team_tendency_snapshots,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles
from player_state_engine.game_intelligence.volume_benchmark import (
    recommend_v014_development,
    run_v013_drive_volume_benchmark,
    v013_drive_volume_promotion_gate,
)
from tests.test_game_intelligence_v011 import _players, _schedules, _synthetic_pbp


def _patterned_plays() -> pd.DataFrame:
    plays = build_play_intelligence_frame(_synthetic_pbp())
    score_state = np.where(
        plays["score_differential"] <= -8,
        "trailing",
        "neutral",
    )
    plays["seconds_between_plays"] = np.where(
        score_state == "trailing",
        14.0,
        np.where(plays["play_family"].eq("RUSH"), 31.0, 24.0),
    )
    return plays


def _research_inputs():
    plays = _patterned_plays()
    tendencies = build_team_tendency_snapshots(plays)
    enriched = attach_point_in_time_matchup_features(plays, tendencies)
    chronology = enriched["season"] * 25 + enriched["week"]
    train = enriched.loc[chronology < 2026 * 25 + 2]
    play_model = PlayCallModel().fit(train)
    outcome_model = EmpiricalPlayOutcomeModel(min_stratum_plays=2).fit(train)
    opportunity_model = StateConditionedOpportunityModel(prior_strength=4.0).fit(train)
    drive_model = DriveVolumeModel(prior_strength=4.0).fit(train)
    usage = build_player_usage_profiles(
        plays,
        season=2026,
        week=2,
        players=_players(),
    )
    return plays, tendencies, usage, play_model, outcome_model, opportunity_model, drive_model


def test_drive_extraction_and_observed_volume_are_game_team_scoped() -> None:
    plays = _patterned_plays()
    drives = extract_drive_frame(plays)
    observed = observed_drive_volume(plays)
    assert not drives.empty
    assert not observed.empty
    assert {"drives", "plays_per_drive", "seconds_per_play", "mean_start_yardline_100"} <= set(
        observed
    )
    sample = observed.loc[
        observed["game_id"].eq("2026_02_BBB_AAA") & observed["team"].eq("AAA")
    ].iloc[0]
    assert sample["drives"] > 0
    assert sample["plays_per_drive"] > 0


def test_drive_volume_model_uses_only_fitted_history_and_context() -> None:
    plays = _patterned_plays()
    chronology = plays["season"] * 25 + plays["week"]
    train = plays.loc[chronology < 2026 * 25 + 2]
    model = DriveVolumeModel(prior_strength=2.0).fit(train)
    assert model.train_max_season == 2026
    assert model.train_max_week == 1

    trailing = {
        "score_differential": -10.0,
        "game_seconds_remaining": 500.0,
        "yardline_100": 60.0,
    }
    neutral = {
        "score_differential": 0.0,
        "game_seconds_remaining": 2000.0,
        "yardline_100": 60.0,
    }
    trailing_seconds = model.expected_seconds(
        team="AAA",
        state=trailing,
        play_family="DROPBACK",
    )
    neutral_seconds = model.expected_seconds(
        team="AAA",
        state=neutral,
        play_family="DROPBACK",
    )
    assert trailing_seconds < neutral_seconds


def test_pace_permutation_preserves_team_season_distribution() -> None:
    plays = _patterned_plays()
    permuted = permute_pace_targets_within_team_season(plays, seed=19)
    for key, original in plays.groupby(["season", "posteam"], sort=False):
        challenger = permuted.loc[
            (permuted["season"] == key[0]) & permuted["posteam"].eq(key[1])
        ]
        assert sorted(original["seconds_between_plays"].tolist()) == sorted(
            challenger["seconds_between_plays"].tolist()
        )
    assert not permuted["seconds_between_plays"].equals(plays["seconds_between_plays"])


def test_volume_probe_is_deterministic_and_tracks_drive_metrics() -> None:
    (
        _,
        tendencies,
        usage,
        play_model,
        outcome_model,
        opportunity_model,
        drive_model,
    ) = _research_inputs()
    matchup = MatchupSpec(
        season=2026,
        week=2,
        home_team="AAA",
        away_team="BBB",
        game_id="2026_02_BBB_AAA",
        home_spread=-2.5,
        game_total=46.0,
    )
    config = SimulationConfig(simulations=3, max_plays=60, seed=23)
    first = simulate_matchup_volume_probe(
        matchup,
        tendencies=tendencies,
        usage=usage,
        outcome_model=outcome_model,
        play_call_model=play_model,
        opportunity_model=opportunity_model,
        drive_volume_model=drive_model,
        league_config=LeagueConfig(),
        config=config,
    )
    second = simulate_matchup_volume_probe(
        matchup,
        tendencies=tendencies,
        usage=usage,
        outcome_model=outcome_model,
        play_call_model=play_model,
        opportunity_model=opportunity_model,
        drive_volume_model=drive_model,
        league_config=LeagueConfig(),
        config=config,
    )
    pd.testing.assert_frame_equal(first.team_draws, second.team_draws)
    pd.testing.assert_frame_equal(first.player_draws, second.player_draws)
    assert {
        "drives",
        "plays_per_drive",
        "seconds_per_play",
        "mean_start_yardline_100",
    } <= set(first.team_draws)
    assert first.diagnostics["component_rng_streams"] is True
    assert first.diagnostics["drive_volume_model"].endswith("v013")
    assert first.diagnostics["production_projection_changed"] is False


def test_drive_volume_evaluator_detects_missing_accuracy() -> None:
    predicted = pd.DataFrame(
        {
            "game_id": ["g", "g"],
            "simulation": [0, 0],
            "team": ["A", "B"],
            "drives": [10.0, 10.0],
            "plays_per_drive": [6.0, 6.0],
            "seconds_per_play": [28.0, 28.0],
            "mean_start_yardline_100": [75.0, 75.0],
        }
    )
    observed = pd.DataFrame(
        {
            "game_id": ["g", "g"],
            "team": ["A", "B"],
            "drives": [12.0, 8.0],
            "plays_per_drive": [5.0, 7.0],
            "seconds_per_play": [24.0, 32.0],
            "mean_start_yardline_100": [70.0, 80.0],
        }
    )
    metrics = evaluate_drive_volume_draws(predicted, observed)
    assert metrics["team_drives_mae"] == 2.0
    assert metrics["team_plays_per_drive_mae"] == 1.0
    assert metrics["team_seconds_per_play_mae"] == 4.0
    assert metrics["team_start_yardline_mae"] == 5.0


def test_v013_benchmark_exposes_eight_cells_and_fails_closed_small_sample() -> None:
    result = run_v013_drive_volume_benchmark(
        _synthetic_pbp(),
        _schedules(),
        test_seasons=(2026,),
        week_start=2,
        week_end=2,
        players=_players(),
        league_config=LeagueConfig(),
        simulations_per_game=1,
        max_games_per_week=1,
        seed=11,
        opportunity_prior_strength=4.0,
        drive_prior_strength=4.0,
    )
    assert len(result.aggregate_metrics) == 8
    assert {
        "learned_state_legacy",
        "learned_state_drive",
        "profile_static_legacy",
        "profile_static_drive",
    } <= set(result.aggregate_metrics)
    assert result.diagnostics["protocol"] == "v013_drive_volume_eight_cell_expanding_weekly"
    assert result.diagnostics["component_rng_streams"] is True
    assert not result.weekly_pace_metrics.empty

    decision = v013_drive_volume_promotion_gate(result)
    assert decision.promoted is False
    assert any("held-out seasons" in reason for reason in decision.reasons)
    recommendation = recommend_v014_development(result)
    assert recommendation["research_only"] is True
    assert recommendation["next_experiment"]
