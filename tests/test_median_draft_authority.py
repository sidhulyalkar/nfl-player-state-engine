from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.draft import DraftState, build_live_draft_board
from player_state_engine.fantasy.draft_advisor import build_reliable_live_draft_board
from player_state_engine.fantasy.league import LeagueConfig


def _league(*, median_scoring: bool) -> LeagueConfig:
    return LeagueConfig(
        teams=2,
        scoring="half_ppr",
        median_scoring=median_scoring,
        roster_slots={"WR": 1, "BENCH": 1},
        replacement_buffer=0,
        replacement_buffer_fraction=0.0,
        risk_preference=1.0,
        bench_value_weight=0.0,
    )


def _q50_only_frame(config: LeagueConfig) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    values = {
        "alpha": (80.0, 160.0, 210.0, 1.0),
        "beta": (20.0, 150.0, 300.0, 2.0),
        "gamma": (70.0, 110.0, 150.0, 3.0),
        "delta": (60.0, 100.0, 140.0, 4.0),
    }
    for player_id, (q10, q50, q90, adp) in values.items():
        rows.append(
            {
                "scoring_contract_id": config.scoring_contract_id,
                "player_id": player_id,
                "player_name": player_id.title(),
                "position": "WR",
                "season_points_q10": q10,
                "season_points_q50": q50,
                "season_points_q90": q90,
                "league_season_points_q10": q10,
                "league_season_points_q50": q50,
                "league_season_points_q90": q90,
                "league_scoring_exact": True,
                "decision_quantile_policy": "q50_only",
                "market_adp": adp,
                "model_version": "0.17.0-test",
            }
        )
    return pd.DataFrame(rows)


def _state() -> DraftState:
    return DraftState(
        teams=2,
        draft_slot=1,
        current_pick=1,
        total_rounds=2,
    )


def _mutate_rejected_tails(frame: pd.DataFrame) -> pd.DataFrame:
    mutated = frame.copy()
    mutated["season_points_q10"] = [-1000.0, -500.0, -50.0, -5.0]
    mutated["season_points_q90"] = [5000.0, 9000.0, 2000.0, 1000.0]
    mutated["league_season_points_q10"] = mutated["season_points_q10"]
    mutated["league_season_points_q90"] = mutated["season_points_q90"]
    return mutated


def _ordered(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values("player_id", kind="mergesort").reset_index(drop=True)


def test_unqualified_median_flag_cannot_change_live_draft_scores_or_actions() -> None:
    median = _league(median_scoring=True)
    nonmedian = _league(median_scoring=False)
    frame = _q50_only_frame(median)

    median_board = _ordered(build_live_draft_board(frame, median, _state()))
    nonmedian_board = _ordered(build_live_draft_board(frame, nonmedian, _state()))

    pd.testing.assert_series_equal(
        median_board["live_draft_score"],
        nonmedian_board["live_draft_score"],
        check_names=False,
    )
    pd.testing.assert_series_equal(
        median_board["ranking_challenger_score"],
        nonmedian_board["ranking_challenger_score"],
        check_names=False,
    )
    pd.testing.assert_series_equal(
        median_board["live_rank"],
        nonmedian_board["live_rank"],
        check_names=False,
    )
    pd.testing.assert_series_equal(
        median_board["draft_action"],
        nonmedian_board["draft_action"],
        check_names=False,
    )
    assert median_board["median_scoring_requested"].all()
    assert not median_board["median_policy_applied"].any()
    assert set(median_board["median_policy_authority"]) == {"none"}
    assert median_board["median_format_score"].eq(0.5).all()
    assert not median_board["median_scoring_boost"].any()
    assert not median_board["draft_reasons"].str.contains("weekly floor", regex=False).any()


def test_q50_only_rejected_tails_cannot_change_median_live_draft_board() -> None:
    config = _league(median_scoring=True)
    frame = _q50_only_frame(config)
    mutated = _mutate_rejected_tails(frame)

    baseline = _ordered(build_live_draft_board(frame, config, _state()))
    changed = _ordered(build_live_draft_board(mutated, config, _state()))

    for column in (
        "decision_value",
        "decision_specific_score",
        "live_draft_score",
        "ranking_challenger_score",
        "live_rank",
        "challenger_rank",
        "draft_action",
        "draft_reasons",
    ):
        pd.testing.assert_series_equal(baseline[column], changed[column], check_names=False)


def test_q50_only_rejected_tails_cannot_change_reliable_room_decision() -> None:
    config = _league(median_scoring=True)
    frame = _q50_only_frame(config)
    mutated = _mutate_rejected_tails(frame)

    baseline = _ordered(
        build_reliable_live_draft_board(
            frame,
            config,
            _state(),
            room_simulations=200,
            room_seed=17,
            projection_age_hours=1.0,
        )
    )
    changed = _ordered(
        build_reliable_live_draft_board(
            mutated,
            config,
            _state(),
            room_simulations=200,
            room_seed=17,
            projection_age_hours=1.0,
        )
    )

    for column in (
        "live_draft_score",
        "room_challenger_score",
        "draft_reliability_score",
        "room_rank",
        "guarded_draft_action",
        "draft_reliability_reasons",
    ):
        pd.testing.assert_series_equal(baseline[column], changed[column], check_names=False)
    assert not baseline["median_policy_applied"].any()
    assert set(baseline["median_policy_authority"]) == {"none"}
