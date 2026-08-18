from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.game_intelligence.benchmark import (
    run_expanding_game_benchmark,
    v011_research_promotion_gate,
)
from player_state_engine.game_intelligence.blend import (
    QuantileBlendCalibrator,
    align_projection_frames,
    expanding_quantile_blend_benchmark,
)
from player_state_engine.game_intelligence.opportunity import (
    StateConditionedOpportunityModel,
    evaluate_opportunity_event_scores,
)
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame


def _synthetic_pbp() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    games = [(2025, 17), (2025, 18), (2026, 1), (2026, 2)]
    for season, week in games:
        game_id = f"{season}_{week:02d}_BBB_AAA"
        for play in range(96):
            team = "AAA" if (play // 12) % 2 == 0 else "BBB"
            defense = "BBB" if team == "AAA" else "AAA"
            local = play % 12
            is_pass = int(local < (8 if team == "AAA" else 6))
            down = local % 4 + 1
            ydstogo = float(2 + local % 10)
            red_zone = play % 16 >= 12
            receiver = None
            rusher = None
            if is_pass:
                if team == "AAA":
                    receiver = "AAA_WR1" if red_zone or local % 3 else "AAA_WR2"
                else:
                    receiver = "BBB_WR1" if local % 2 else "BBB_WR2"
            else:
                if team == "AAA":
                    rusher = "AAA_RB1" if red_zone or local % 3 else "AAA_RB2"
                else:
                    rusher = "BBB_RB1" if local % 2 else "BBB_RB2"
            yards = 7.0 if is_pass else 4.0
            rows.append(
                {
                    "season": season,
                    "week": week,
                    "game_id": game_id,
                    "play_id": play + 1,
                    "drive": play // 12 + 1,
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
                    "yardline_100": float(15 if red_zone else 72 - (local * 3)),
                    "qtr": min(4, play // 24 + 1),
                    "game_seconds_remaining": float(max(1, 3600 - play * 36)),
                    "score_differential": float(-10 if play > 72 and team == "AAA" else 0),
                    "goal_to_go": int(red_zone),
                    "shotgun": is_pass,
                    "no_huddle": int(play % 9 == 0),
                    "yards_gained": yards,
                    "touchdown": int(play in {15, 47, 79}),
                    "first_down": int(yards >= ydstogo),
                    "complete_pass": is_pass,
                    "interception": 0,
                    "fumble_lost": 0,
                    "epa": 0.12 if is_pass else 0.02,
                    "passer_player_id": f"{team}_QB" if is_pass else None,
                    "receiver_player_id": receiver,
                    "rusher_player_id": rusher,
                    "spread_line": -2.5,
                    "total_line": 46.0,
                }
            )
    return pd.DataFrame(rows)


def _players() -> pd.DataFrame:
    ids = [
        "AAA_QB",
        "AAA_WR1",
        "AAA_WR2",
        "AAA_RB1",
        "AAA_RB2",
        "BBB_QB",
        "BBB_WR1",
        "BBB_WR2",
        "BBB_RB1",
        "BBB_RB2",
    ]
    positions = ["QB", "WR", "WR", "RB", "RB", "QB", "WR", "WR", "RB", "RB"]
    return pd.DataFrame({"gsis_id": ids, "position": positions})


def _schedules() -> pd.DataFrame:
    rows = []
    for season, week in ((2025, 17), (2025, 18), (2026, 1), (2026, 2)):
        rows.append(
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
        )
    return pd.DataFrame(rows)


def test_state_conditioned_opportunity_uses_only_fitted_history() -> None:
    plays = build_play_intelligence_frame(_synthetic_pbp())
    chronology = plays["season"] * 25 + plays["week"]
    train = plays.loc[chronology < 2026 * 25 + 2]
    test = plays.loc[(plays["season"] == 2026) & (plays["week"] == 2)]
    model = StateConditionedOpportunityModel(prior_strength=4.0).fit(train)

    assert model.train_max_season == 2026
    assert model.train_max_week == 1

    red_zone_state = test.loc[
        test["posteam"].eq("AAA")
        & test["play_family"].eq("DROPBACK")
        & (test["yardline_100"] <= 20)
    ].iloc[0]
    distribution = model.distribution(
        team="AAA", opportunity_type="target", state=red_zone_state, use_context=True
    ).set_index("player_id")
    assert distribution.loc["AAA_WR1", "probability"] > distribution.loc[
        "AAA_WR1", "base_probability"
    ]

    scores = model.score_events(test)
    metrics = evaluate_opportunity_event_scores(scores)
    assert metrics["event_rows"] > 0
    assert np.isfinite(metrics["state_conditioned_log_loss"])
    assert metrics["mean_context_evidence"] > 0


def test_expanding_benchmark_retrains_at_each_week_cutoff() -> None:
    result = run_expanding_game_benchmark(
        _synthetic_pbp(),
        _schedules(),
        test_seasons=(2026,),
        week_start=1,
        week_end=2,
        players=_players(),
        simulations_per_game=2,
        max_games_per_week=1,
        seed=7,
        opportunity_prior_strength=4.0,
    )
    assert list(result.weekly_game_metrics["week"]) == [1, 2]
    assert result.diagnostics["protocol"] == "expanding_weekly_point_in_time_v011"
    assert result.diagnostics["game_folds"] == 2
    assert not result.weekly_opportunity_metrics.empty

    decision = v011_research_promotion_gate(result)
    assert decision.promoted is False
    assert any("held-out seasons" in reason for reason in decision.reasons)
    assert any("fantasy" in reason for reason in decision.reasons)


def _blend_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    direct_rows: list[dict[str, object]] = []
    generative_rows: list[dict[str, object]] = []
    actual_rows: list[dict[str, object]] = []
    player_index = 0
    for season, weeks in ((2025, range(1, 7)), (2026, range(1, 4))):
        for week in weeks:
            for player in range(40):
                player_index += 1
                player_id = f"P{player:02d}"
                position = "WR" if player % 2 else "RB"
                actual = 8.0 + (player % 10) + week * 0.2
                direct_median = actual + (0.4 if player % 3 else -0.3)
                generative_median = actual + (2.0 if player % 2 else -1.5)
                direct_rows.append(
                    {
                        "season": season,
                        "week": week,
                        "player_id": player_id,
                        "q10": direct_median - 4.0,
                        "q50": direct_median,
                        "q90": direct_median + 4.0,
                    }
                )
                generative_rows.append(
                    {
                        "season": season,
                        "week": week,
                        "player_id": player_id,
                        "position": position,
                        "q10": generative_median - 5.0,
                        "q50": generative_median,
                        "q90": generative_median + 5.0,
                    }
                )
                actual_rows.append(
                    {
                        "season": season,
                        "week": week,
                        "player_id": player_id,
                        "position": position,
                        "fantasy_points": actual,
                    }
                )
    return pd.DataFrame(direct_rows), pd.DataFrame(generative_rows), pd.DataFrame(actual_rows)


def test_quantile_blend_weights_are_learned_only_from_prior_rows() -> None:
    direct, generative, actuals = _blend_frames()
    aligned = align_projection_frames(direct, generative, actuals)
    chronology = aligned["season"] * 25 + aligned["week"]
    history = aligned.loc[chronology < 2026 * 25 + 1]
    future = aligned.loc[(aligned["season"] == 2026) & (aligned["week"] == 1)]

    calibrator = QuantileBlendCalibrator(min_position_rows=50).fit(history)
    assert calibrator.global_direct_weight >= 0.5
    transformed = calibrator.transform(future)
    assert (transformed["blend_q10"] <= transformed["blend_q50"]).all()
    assert (transformed["blend_q50"] <= transformed["blend_q90"]).all()

    result = expanding_quantile_blend_benchmark(
        direct,
        generative,
        actuals,
        test_seasons=(2026,),
        week_start=1,
        week_end=3,
        min_history_rows=100,
        min_position_rows=50,
    )
    assert len(result.weekly_metrics) == 3
    assert result.diagnostics["protocol"] == "expanding_quantile_blend_v011"
    blend = result.aggregate_metrics.loc[result.aggregate_metrics["model"].eq("blend")].iloc[0]
    generative_metric = result.aggregate_metrics.loc[
        result.aggregate_metrics["model"].eq("generative")
    ].iloc[0]
    assert blend["pinball_loss"] < generative_metric["pinball_loss"]
