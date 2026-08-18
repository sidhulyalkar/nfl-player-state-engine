from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.drive import DriveVolumeModel
from player_state_engine.game_intelligence.drive_simulator import simulate_matchup_volume_probe
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.opportunity import StateConditionedOpportunityModel
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.schema import MatchupSpec, SimulationConfig
from player_state_engine.game_intelligence.tendencies import (
    attach_point_in_time_matchup_features,
    build_team_tendency_snapshots,
)
from player_state_engine.game_intelligence.transition import (
    PossessionTransitionModel,
    build_possession_transition_frame,
    evaluate_field_goal_scores,
    evaluate_transition_event_scores,
    extract_field_goal_attempts,
    observed_transition_team_games,
    permute_field_goal_results_within_distance_season,
    permute_transition_targets_within_type_season,
)
from player_state_engine.game_intelligence.transition_benchmark import (
    recommend_v015_development,
    run_v014_transition_benchmark,
    v014_transition_promotion_gate,
)
from player_state_engine.game_intelligence.transition_simulator import (
    simulate_matchup_transition_probe,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles
from tests.test_game_intelligence_v011 import _players


def _next_start(previous_kind: int, next_team: str) -> float:
    if previous_kind == 0:
        return 86.0 if next_team == "AAA" else 74.0
    if previous_kind == 1:
        return 76.0
    if previous_kind == 2:
        return 62.0
    if previous_kind == 3:
        return 58.0 if next_team == "AAA" else 66.0
    if previous_kind == 4:
        return 75.0
    return 55.0 if next_team == "AAA" else 63.0


def _transition_pbp() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    games = ((2025, 17), (2025, 18), (2026, 1), (2026, 2))
    for season, week in games:
        game_id = f"{season}_{week:02d}_BBB_AAA"
        clock = 3600.0
        play_id = 1
        previous_kind: int | None = None
        for possession in range(20):
            team = "AAA" if possession % 2 == 0 else "BBB"
            defense = "BBB" if team == "AAA" else "AAA"
            start_yardline = 75.0 if previous_kind is None else _next_start(previous_kind, team)
            kind = possession % 6

            for local in range(2):
                is_pass = int(local == 0)
                terminal = local == 1
                touchdown = int(terminal and kind == 4)
                interception = int(terminal and kind == 3)
                first_down = int(local == 0)
                rows.append(
                    {
                        "season": season,
                        "week": week,
                        "game_id": game_id,
                        "play_id": play_id,
                        "drive": possession + 1,
                        "home_team": "AAA",
                        "away_team": "BBB",
                        "posteam": team,
                        "defteam": defense,
                        "pass_attempt": is_pass,
                        "rush_attempt": 1 - is_pass,
                        "qb_dropback": is_pass,
                        "sack": 0,
                        "qb_scramble": 0,
                        "down": 1 if local == 0 else 4,
                        "ydstogo": 7.0,
                        "yardline_100": start_yardline if local == 0 else max(5.0, start_yardline - 6.0),
                        "qtr": min(4, 1 + int((3600.0 - clock) // 900.0)),
                        "game_seconds_remaining": clock,
                        "score_differential": 0.0,
                        "goal_to_go": 0,
                        "shotgun": is_pass,
                        "no_huddle": 0,
                        "yards_gained": 6.0,
                        "touchdown": touchdown,
                        "first_down": first_down,
                        "complete_pass": is_pass,
                        "interception": interception,
                        "fumble_lost": 0,
                        "epa": 0.05,
                        "passer_player_id": f"{team}_QB" if is_pass else None,
                        "receiver_player_id": f"{team}_WR1" if is_pass else None,
                        "rusher_player_id": f"{team}_RB1" if not is_pass else None,
                        "spread_line": -2.5,
                        "total_line": 46.0,
                        "play_type": "pass" if is_pass else "run",
                        "punt_attempt": 0,
                        "field_goal_attempt": 0,
                        "field_goal_result": None,
                    }
                )
                play_id += 1
                clock -= 18.0 if is_pass else 12.0

            if kind == 0:
                rows.append(
                    {
                        "season": season,
                        "week": week,
                        "game_id": game_id,
                        "play_id": play_id,
                        "drive": possession + 1,
                        "home_team": "AAA",
                        "away_team": "BBB",
                        "posteam": team,
                        "defteam": defense,
                        "pass_attempt": 0,
                        "rush_attempt": 0,
                        "qb_dropback": 0,
                        "sack": 0,
                        "qb_scramble": 0,
                        "down": 4,
                        "ydstogo": 7.0,
                        "yardline_100": max(5.0, start_yardline - 6.0),
                        "qtr": min(4, 1 + int((3600.0 - clock) // 900.0)),
                        "game_seconds_remaining": clock,
                        "score_differential": 0.0,
                        "yards_gained": 0.0,
                        "touchdown": 0,
                        "first_down": 0,
                        "complete_pass": 0,
                        "interception": 0,
                        "fumble_lost": 0,
                        "epa": -0.2,
                        "play_type": "punt",
                        "punt_attempt": 1,
                        "field_goal_attempt": 0,
                        "field_goal_result": None,
                    }
                )
                play_id += 1
                clock -= 8.0
            elif kind in {1, 2}:
                made = kind == 1
                rows.append(
                    {
                        "season": season,
                        "week": week,
                        "game_id": game_id,
                        "play_id": play_id,
                        "drive": possession + 1,
                        "home_team": "AAA",
                        "away_team": "BBB",
                        "posteam": team,
                        "defteam": defense,
                        "pass_attempt": 0,
                        "rush_attempt": 0,
                        "qb_dropback": 0,
                        "sack": 0,
                        "qb_scramble": 0,
                        "down": 4,
                        "ydstogo": 7.0,
                        "yardline_100": 28.0 if made else 38.0,
                        "qtr": min(4, 1 + int((3600.0 - clock) // 900.0)),
                        "game_seconds_remaining": clock,
                        "score_differential": 0.0,
                        "yards_gained": 0.0,
                        "touchdown": 0,
                        "first_down": 0,
                        "complete_pass": 0,
                        "interception": 0,
                        "fumble_lost": 0,
                        "epa": 0.4 if made else -0.4,
                        "play_type": "field_goal",
                        "punt_attempt": 0,
                        "field_goal_attempt": 1,
                        "field_goal_result": "good" if made else "missed",
                        "kick_distance": 45.0 if made else 55.0,
                    }
                )
                play_id += 1
                clock -= 5.0
            clock -= 4.0
            previous_kind = kind
    return pd.DataFrame(rows)


def _transition_schedules() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": season,
                "week": week,
                "game_id": f"{season}_{week:02d}_BBB_AAA",
                "home_team": "AAA",
                "away_team": "BBB",
                "home_score": 24,
                "away_score": 20,
                "spread_line": -2.5,
                "total_line": 46.0,
            }
            for season, week in ((2025, 17), (2025, 18), (2026, 1), (2026, 2))
        ]
    )


def _research_inputs():
    raw = _transition_pbp()
    plays = build_play_intelligence_frame(raw)
    tendencies = build_team_tendency_snapshots(plays)
    enriched = attach_point_in_time_matchup_features(plays, tendencies)
    chronology = enriched["season"] * 25 + enriched["week"]
    train = enriched.loc[chronology < 2026 * 25 + 2]
    raw_chronology = raw["season"] * 25 + raw["week"]
    raw_train = raw.loc[raw_chronology < 2026 * 25 + 2]
    play_model = PlayCallModel().fit(train)
    outcome_model = EmpiricalPlayOutcomeModel(min_stratum_plays=2).fit(train)
    opportunity_model = StateConditionedOpportunityModel(prior_strength=4.0).fit(train)
    drive_model = DriveVolumeModel(prior_strength=4.0).fit(train)
    transition_model = PossessionTransitionModel(prior_strength=2.0).fit(raw_train)
    usage = build_player_usage_profiles(
        plays,
        season=2026,
        week=2,
        players=_players(),
    )
    return (
        raw,
        tendencies,
        usage,
        play_model,
        outcome_model,
        opportunity_model,
        drive_model,
        transition_model,
    )


def _matchup() -> MatchupSpec:
    return MatchupSpec(
        season=2026,
        week=2,
        home_team="AAA",
        away_team="BBB",
        game_id="2026_02_BBB_AAA",
        home_spread=-2.5,
        game_total=46.0,
    )


def test_transition_extractor_uses_terminal_special_teams_event() -> None:
    raw = _transition_pbp()
    transitions = build_possession_transition_frame(raw)
    assert not transitions.empty
    assert {
        "PUNT",
        "FIELD_GOAL_GOOD",
        "FIELD_GOAL_MISSED",
        "TURNOVER",
        "TOUCHDOWN",
        "DOWNS",
    } <= set(transitions["transition_type"])
    punt = transitions.loc[transitions["transition_type"].eq("PUNT")].iloc[0]
    assert punt["transition_seconds"] < 20.0
    assert punt["next_start_yardline_100"] in {74.0, 86.0}


def test_raw_observed_counts_include_final_special_teams_event() -> None:
    raw = _transition_pbp()
    final_game = raw["game_id"].iloc[-1]
    final_team = raw.loc[raw["game_id"].eq(final_game), "posteam"].dropna().iloc[-1]
    observed = observed_transition_team_games(raw)
    row = observed.loc[
        observed["game_id"].eq(final_game) & observed["team"].eq(str(final_team))
    ].iloc[0]
    assert row["punts"] + row["field_goal_attempts"] + row["turnovers"] >= 0.0
    raw_events = raw.loc[raw["game_id"].eq(final_game) & raw["posteam"].eq(final_team)]
    assert row["punts"] == float(raw_events["punt_attempt"].fillna(0).sum())
    assert row["field_goal_attempts"] == float(raw_events["field_goal_attempt"].fillna(0).sum())


def test_transition_permutations_preserve_group_marginals() -> None:
    raw = _transition_pbp()
    transitions = build_possession_transition_frame(raw)
    permuted = permute_transition_targets_within_type_season(transitions, seed=17)
    for key, original in transitions.groupby(["season", "transition_type"], sort=False):
        challenger = permuted.loc[
            (permuted["season"] == key[0]) & permuted["transition_type"].eq(key[1])
        ]
        assert sorted(original["next_start_yardline_100"].tolist()) == sorted(
            challenger["next_start_yardline_100"].tolist()
        )

    attempts = extract_field_goal_attempts(raw)
    shuffled = permute_field_goal_results_within_distance_season(attempts, seed=17)
    for key, original in attempts.groupby(["season", "distance_bucket"], sort=False):
        challenger = shuffled.loc[
            (shuffled["season"] == key[0]) & shuffled["distance_bucket"].eq(key[1])
        ]
        assert sorted(original["made"].tolist()) == sorted(challenger["made"].tolist())


def test_transition_model_is_point_in_time_and_scores_finite() -> None:
    raw = _transition_pbp()
    chronology = raw["season"] * 25 + raw["week"]
    train = raw.loc[chronology < 2026 * 25 + 2]
    test = raw.loc[(raw["season"] == 2026) & (raw["week"] == 2)]
    model = PossessionTransitionModel(prior_strength=2.0).fit(train)
    assert model.train_max_season == 2026
    assert model.train_max_week == 1
    transition_metrics = evaluate_transition_event_scores(model.score_transition_events(test))
    field_goal_metrics = evaluate_field_goal_scores(model.score_field_goals(test))
    assert np.isfinite(transition_metrics["transition_start_yardline_mae"])
    assert np.isfinite(transition_metrics["transition_seconds_mae"])
    assert np.isfinite(field_goal_metrics["field_goal_log_loss"])


def test_instrumented_transition_off_probe_matches_frozen_v013_core_draws() -> None:
    (
        _,
        tendencies,
        usage,
        play_model,
        outcome_model,
        opportunity_model,
        drive_model,
        _,
    ) = _research_inputs()
    config = SimulationConfig(simulations=3, max_plays=60, seed=29)
    frozen = simulate_matchup_volume_probe(
        _matchup(),
        tendencies=tendencies,
        usage=usage,
        outcome_model=outcome_model,
        play_call_model=play_model,
        opportunity_model=opportunity_model,
        drive_volume_model=drive_model,
        league_config=LeagueConfig(),
        config=config,
    )
    instrumented = simulate_matchup_transition_probe(
        _matchup(),
        tendencies=tendencies,
        usage=usage,
        outcome_model=outcome_model,
        play_call_model=play_model,
        opportunity_model=opportunity_model,
        drive_volume_model=drive_model,
        transition_model=None,
        league_config=LeagueConfig(),
        config=config,
    )
    pd.testing.assert_frame_equal(frozen.game_draws, instrumented.game_draws)
    pd.testing.assert_frame_equal(frozen.player_draws, instrumented.player_draws)
    common = list(frozen.team_draws.columns)
    pd.testing.assert_frame_equal(frozen.team_draws, instrumented.team_draws[common])


def test_transition_probe_is_deterministic_and_tracks_special_teams() -> None:
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
    config = SimulationConfig(simulations=3, max_plays=60, seed=29)
    kwargs = {
        "tendencies": tendencies,
        "usage": usage,
        "outcome_model": outcome_model,
        "play_call_model": play_model,
        "opportunity_model": opportunity_model,
        "drive_volume_model": drive_model,
        "transition_model": transition_model,
        "league_config": LeagueConfig(),
        "config": config,
    }
    first = simulate_matchup_transition_probe(_matchup(), **kwargs)
    second = simulate_matchup_transition_probe(_matchup(), **kwargs)
    pd.testing.assert_frame_equal(first.team_draws, second.team_draws)
    pd.testing.assert_frame_equal(first.player_draws, second.player_draws)
    assert {
        "punts",
        "field_goal_attempts",
        "field_goals_made",
        "turnovers",
        "turnovers_on_downs",
    } <= set(first.team_draws)
    assert first.diagnostics["component_rng_base_version"] == 13
    assert first.diagnostics["transition_rng_stream_added"] is True
    assert first.diagnostics["transition_model"].endswith("v014")
    assert first.diagnostics["production_projection_changed"] is False


def test_v014_benchmark_exposes_four_cells_and_fails_closed_small_sample() -> None:
    result = run_v014_transition_benchmark(
        _transition_pbp(),
        _transition_schedules(),
        test_seasons=(2026,),
        week_start=2,
        week_end=2,
        players=_players(),
        league_config=LeagueConfig(),
        simulations_per_game=1,
        max_games_per_week=1,
        seed=13,
        opportunity_prior_strength=4.0,
        drive_prior_strength=4.0,
        transition_prior_strength=2.0,
    )
    assert set(result.aggregate_metrics) == {
        "legacy_drive_legacy_transition",
        "drive_legacy_transition",
        "legacy_drive_transition",
        "drive_transition",
    }
    assert result.diagnostics["protocol"] == "v014_possession_transition_four_cell_expanding_weekly"
    assert result.diagnostics["raw_special_teams_evidence"] is True
    assert not result.weekly_isolated_metrics.empty

    decision = v014_transition_promotion_gate(result)
    assert decision.promoted is False
    assert any("held-out seasons" in reason for reason in decision.reasons)
    recommendation = recommend_v015_development(result)
    assert recommendation["research_only"] is True
    assert recommendation["production_projection_changed"] is False


def test_transition_model_fails_closed_on_missing_schema() -> None:
    bad = pd.DataFrame({"season": [2026], "week": [1]})
    try:
        build_possession_transition_frame(bad)
    except ValueError as exc:
        assert "missing columns" in str(exc).lower()
    else:
        raise AssertionError("transition extraction should fail closed on missing schema")
