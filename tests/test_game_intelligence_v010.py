from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from player_state_engine.game_intelligence.coaching import (
    resolve_coach_matchup_prior,
    resolve_game_coach_priors,
    resolve_team_play_callers,
)
from player_state_engine.game_intelligence.evaluation import game_simulation_promotion_gate
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.sources import game_evidence_catalog
from player_state_engine.game_intelligence.tendencies import (
    attach_point_in_time_matchup_features,
    build_team_tendency_snapshots,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles


def synthetic_pbp() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    games = [(2025, 17), (2025, 18), (2026, 1), (2026, 2)]
    for season, week in games:
        game_id = f"{season}_{week:02d}_BBB_AAA"
        for play in range(80):
            team = "AAA" if (play // 10) % 2 == 0 else "BBB"
            defense = "BBB" if team == "AAA" else "AAA"
            team_index = play % 10
            pass_threshold = 7 if team == "AAA" else 4
            is_pass = int(team_index < pass_threshold)
            yards = 8.0 if is_pass else 5.0
            down = play % 4 + 1
            ydstogo = float(3 + play % 9)
            rows.append(
                {
                    "season": season,
                    "week": week,
                    "game_id": game_id,
                    "play_id": play + 1,
                    "drive": play // 10 + 1,
                    "home_team": "AAA",
                    "away_team": "BBB",
                    "posteam": team,
                    "defteam": defense,
                    "pass_attempt": is_pass,
                    "rush_attempt": 1 - is_pass,
                    "qb_dropback": is_pass,
                    "sack": 0,
                    "qb_scramble": 0,
                    "down": down,
                    "ydstogo": ydstogo,
                    "yardline_100": float(90 - (play % 18) * 5),
                    "qtr": min(4, play // 20 + 1),
                    "game_seconds_remaining": float(max(1, 3600 - play * 42)),
                    "score_differential": float((play // 20) * (3 if team == "AAA" else -3)),
                    "goal_to_go": 0,
                    "shotgun": is_pass,
                    "no_huddle": int(play % 7 == 0),
                    "yards_gained": yards,
                    "touchdown": int(play in {19, 39, 59, 79}),
                    "first_down": int(yards >= ydstogo),
                    "complete_pass": is_pass,
                    "interception": int(is_pass and play % 67 == 0),
                    "fumble_lost": 0,
                    "epa": 0.15 if is_pass else 0.03,
                    "passer_player_id": f"{team}_QB" if is_pass else None,
                    "receiver_player_id": f"{team}_WR1" if is_pass else None,
                    "rusher_player_id": f"{team}_RB1" if not is_pass else None,
                    "spread_line": -3.0,
                    "total_line": 47.5,
                }
            )
    return pd.DataFrame(rows)


def player_map() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gsis_id": [
                "AAA_QB",
                "AAA_WR1",
                "AAA_RB1",
                "BBB_QB",
                "BBB_WR1",
                "BBB_RB1",
            ],
            "position": ["QB", "WR", "RB", "QB", "WR", "RB"],
        }
    )


def test_team_tendencies_are_shifted_before_current_week() -> None:
    plays = build_play_intelligence_frame(synthetic_pbp())
    snapshots = build_team_tendency_snapshots(plays)
    aaa_w1 = snapshots.loc[
        (snapshots["season"] == 2026) & (snapshots["week"] == 1) & snapshots["team"].eq("AAA")
    ].iloc[0]
    aaa_2025_w18 = snapshots.loc[
        (snapshots["season"] == 2025)
        & (snapshots["week"] == 18)
        & snapshots["team"].eq("AAA")
    ].iloc[0]
    assert aaa_w1["pass_rate_lag1"] == pytest.approx(aaa_2025_w18["pass_rate_actual"])

    enriched = attach_point_in_time_matchup_features(plays, snapshots)
    week_two = enriched.loc[(enriched["season"] == 2026) & (enriched["week"] == 2)]
    assert week_two["pregame_pass_rate"].notna().all()
    assert not any(column.endswith("_actual") for column in PlayCallModel().feature_columns)


def test_week_one_usage_can_reach_prior_season_week_eighteen() -> None:
    plays = build_play_intelligence_frame(synthetic_pbp())
    usage = build_player_usage_profiles(
        plays,
        season=2026,
        week=1,
        players=player_map(),
        lookback_weeks=8,
    )
    assert set(usage["player_id"]) >= {"AAA_QB", "AAA_WR1", "AAA_RB1"}
    aaa = usage.loc[usage["team"].eq("AAA")]
    assert aaa["usage_evidence_weight"].sum() > 0
    assert aaa.loc[aaa["player_id"].eq("AAA_QB"), "position"].iloc[0] == "QB"


def test_play_call_and_outcome_models_fit_only_pre_cutoff_rows() -> None:
    plays = build_play_intelligence_frame(synthetic_pbp())
    snapshots = build_team_tendency_snapshots(plays)
    enriched = attach_point_in_time_matchup_features(plays, snapshots)
    chronology = enriched["season"] * 25 + enriched["week"]
    train = enriched.loc[chronology < 2026 * 25 + 2]
    test = enriched.loc[(enriched["season"] == 2026) & (enriched["week"] == 2)]

    play_model = PlayCallModel().fit(train)
    probability = play_model.predict_pass_probability(test)
    assert np.all((probability >= 0.0) & (probability <= 1.0))
    assert play_model.train_max_season == 2026
    assert play_model.train_max_week == 1

    outcome = EmpiricalPlayOutcomeModel(min_stratum_plays=2).fit(train)
    sampled = outcome.sample(
        play_family="DROPBACK",
        down=1,
        distance_bucket=2,
        field_zone=2,
        rng=np.random.default_rng(7),
    )
    assert "yards_gained" in sampled
    assert np.isfinite(sampled["yards_gained"])


def test_play_caller_matchups_use_only_prior_verified_meetings() -> None:
    coaches = pd.DataFrame(
        {
            "season": [2025, 2025, 2026, 2026],
            "week": [1, 1, 1, 1],
            "team": ["AAA", "BBB", "AAA", "BBB"],
            "offensive_play_caller": ["OC_A", "OC_B", "OC_A", "OC_B"],
            "defensive_play_caller": ["DC_A", "DC_B", "DC_A", "DC_B"],
        }
    )
    history = pd.DataFrame(
        {
            "season": [2025, 2025, 2026],
            "week": [5, 12, 2],
            "game_id": ["g1", "g2", "future_target"],
            "offensive_play_caller_id": ["OC_A", "OC_A", "OC_A"],
            "defensive_play_caller_id": ["DC_B", "DC_B", "DC_B"],
            "pass_rate": [0.60, 0.70, 0.99],
        }
    )
    callers = resolve_team_play_callers(coaches, season=2026, week=2, team="AAA")
    assert callers["offensive_play_caller"] == "OC_A"
    prior = resolve_coach_matchup_prior(
        history,
        offensive_play_caller="OC_A",
        defensive_play_caller="DC_B",
        season=2026,
        week=2,
    )
    assert prior is not None
    assert prior["coach_matchup_games_prior"] == 2
    assert prior["coach_matchup_pass_rate_prior"] == pytest.approx(0.65)
    assert prior["coach_matchup_weight"] == pytest.approx(0.05)

    game_priors = resolve_game_coach_priors(
        coaches,
        history,
        season=2026,
        week=2,
        home_team="AAA",
        away_team="BBB",
    )
    assert game_priors["AAA"] is not None
    assert game_priors["BBB"] is None


def test_retrospective_participation_is_never_cataloged_as_live() -> None:
    catalog = {entry["name"]: entry for entry in game_evidence_catalog()}
    participation = catalog["nflverse_participation"]
    assert str(participation["availability"]) == "retrospective"
    assert participation["point_in_time_safe"] is False
    assert catalog["nflverse_pbp"]["point_in_time_safe"] is True


def test_promotion_gate_fails_closed_when_full_replay_metrics_are_missing() -> None:
    decision = game_simulation_promotion_gate(
        {"games": 200.0, "play_call_log_loss": 0.50},
        {"games": 200.0, "play_call_log_loss": 0.55},
    )
    assert decision.promoted is False
    assert any("missing required team replay metric" in reason for reason in decision.reasons)
    assert any("missing required player replay metric" in reason for reason in decision.reasons)
    assert any("interval coverage" in reason for reason in decision.reasons)
