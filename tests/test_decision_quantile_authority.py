from __future__ import annotations

import pandas as pd
import pytest

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.valuation import (
    Q50_ONLY_POLICY,
    QUALIFIED_DISTRIBUTION_POLICY,
    QUALIFIED_MEDIAN_POLICY_AUTHORITY,
    value_players,
)


def _exact_wr_frame(policy: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": "safe",
                "player_name": "Safe WR",
                "position": "WR",
                "season_points_q10": 80.0,
                "season_points_q50": 150.0,
                "season_points_q90": 170.0,
                "league_season_points_q10": 80.0,
                "league_season_points_q50": 150.0,
                "league_season_points_q90": 170.0,
                "league_scoring_exact": True,
                "decision_quantile_policy": policy,
            },
            {
                "player_id": "volatile",
                "player_name": "Volatile WR",
                "position": "WR",
                "season_points_q10": 20.0,
                "season_points_q50": 150.0,
                "season_points_q90": 260.0,
                "league_season_points_q10": 20.0,
                "league_season_points_q50": 150.0,
                "league_season_points_q90": 260.0,
                "league_scoring_exact": True,
                "decision_quantile_policy": policy,
            },
            {
                "player_id": "replacement",
                "player_name": "Replacement WR",
                "position": "WR",
                "season_points_q10": 60.0,
                "season_points_q50": 100.0,
                "season_points_q90": 140.0,
                "league_season_points_q10": 60.0,
                "league_season_points_q50": 100.0,
                "league_season_points_q90": 140.0,
                "league_scoring_exact": True,
                "decision_quantile_policy": policy,
            },
        ]
    )


def _league(*, median_scoring: bool = False, risk_preference: float = 1.0) -> LeagueConfig:
    return LeagueConfig(
        teams=1,
        scoring="ppr",
        median_scoring=median_scoring,
        risk_preference=risk_preference,
        roster_slots={"WR": 1},
        replacement_buffer=0.0,
        replacement_buffer_fraction=0.0,
    )


def test_q50_only_policy_prevents_unqualified_tails_from_changing_decision_value() -> None:
    valued = value_players(_exact_wr_frame(Q50_ONLY_POLICY), _league()).set_index("player_id")

    assert valued.loc["safe", "decision_value"] == valued.loc["volatile", "decision_value"]
    assert valued.loc["safe", "decision_floor_vorp"] == valued.loc["safe", "vorp"]
    assert valued.loc["volatile", "decision_upside_vorp"] == valued.loc["volatile", "vorp"]
    assert bool(valued.loc["safe", "decision_tail_authorized"]) is False
    assert bool(valued.loc["volatile", "decision_risk_preference_applied"]) is False
    assert pd.isna(valued.loc["safe", "decision_uncertainty"])


def test_q50_only_policy_is_invariant_to_risk_preference() -> None:
    frame = _exact_wr_frame(Q50_ONLY_POLICY)
    risk_averse = value_players(frame, _league(risk_preference=0.0)).set_index("player_id")
    risk_seeking = value_players(frame, _league(risk_preference=1.0)).set_index("player_id")

    pd.testing.assert_series_equal(
        risk_averse["decision_value"].sort_index(),
        risk_seeking["decision_value"].sort_index(),
        check_names=False,
    )


def test_qualified_distribution_policy_can_use_upside_tail() -> None:
    valued = value_players(
        _exact_wr_frame(QUALIFIED_DISTRIBUTION_POLICY),
        _league(risk_preference=1.0),
    ).set_index("player_id")

    assert valued.loc["volatile", "decision_value"] > valued.loc["safe", "decision_value"]
    assert bool(valued.loc["safe", "decision_tail_authorized"]) is True
    assert bool(valued.loc["volatile", "decision_risk_preference_applied"]) is True


def test_median_league_does_not_apply_unvalidated_adjustment() -> None:
    frame = _exact_wr_frame(Q50_ONLY_POLICY)
    nonmedian = value_players(frame, _league(median_scoring=False)).set_index("player_id")
    median_unqualified = value_players(frame, _league(median_scoring=True)).set_index("player_id")

    assert median_unqualified.loc["safe", "decision_value"] == nonmedian.loc["safe", "decision_value"]
    assert not median_unqualified["median_policy_applied"].any()
    assert set(median_unqualified["median_policy_authority"]) == {"none"}
    assert median_unqualified["decision_median_adjustment"].eq(0.0).all()


def test_qualified_median_authority_requires_replay_derived_adjustment() -> None:
    with pytest.raises(ValueError, match="replay-derived median_policy_adjustment"):
        value_players(
            _exact_wr_frame(QUALIFIED_DISTRIBUTION_POLICY),
            _league(median_scoring=True),
            median_policy_authority=QUALIFIED_MEDIAN_POLICY_AUTHORITY,
        )


def test_replay_derived_median_adjustment_is_applied_exactly() -> None:
    frame = _exact_wr_frame(QUALIFIED_DISTRIBUTION_POLICY)
    frame["median_policy_adjustment"] = [3.0, -2.0, 0.0]
    unqualified = value_players(frame, _league(median_scoring=True)).set_index("player_id")
    qualified = value_players(
        frame,
        _league(median_scoring=True),
        median_policy_authority=QUALIFIED_MEDIAN_POLICY_AUTHORITY,
    ).set_index("player_id")

    for player_id, adjustment in {"safe": 3.0, "volatile": -2.0, "replacement": 0.0}.items():
        assert qualified.loc[player_id, "decision_median_adjustment"] == adjustment
        assert qualified.loc[player_id, "decision_value"] - unqualified.loc[player_id, "decision_value"] == pytest.approx(adjustment)
    assert qualified["median_policy_applied"].all()
    assert set(qualified["median_policy_authority"]) == {QUALIFIED_MEDIAN_POLICY_AUTHORITY}


def test_unknown_explicit_decision_quantile_policy_fails_closed() -> None:
    frame = _exact_wr_frame("mystery_policy")
    with pytest.raises(ValueError, match="Unsupported decision_quantile_policy"):
        value_players(frame, _league())


def test_unknown_median_policy_authority_fails_closed() -> None:
    with pytest.raises(ValueError, match="Unsupported median_policy_authority"):
        value_players(
            _exact_wr_frame(Q50_ONLY_POLICY),
            _league(median_scoring=True),
            median_policy_authority="trust_me",
        )
