from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import prepare_league_scoring_quantiles
from player_state_engine.fantasy.valuation import value_players


def _receiver_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": ["wr1", "wr2"],
            "player_name": ["Volume WR", "Low Volume WR"],
            "position": ["WR", "WR"],
            "season_points_q10": [100.0, 90.0],
            "season_points_q50": [180.0, 170.0],
            "season_points_q90": [260.0, 250.0],
            "rushing_yards_q10": [0.0, 0.0],
            "rushing_yards_q50": [0.0, 0.0],
            "rushing_yards_q90": [0.0, 0.0],
            "rushing_tds_q10": [0.0, 0.0],
            "rushing_tds_q50": [0.0, 0.0],
            "rushing_tds_q90": [0.0, 0.0],
            "receptions_q10": [60.0, 30.0],
            "receptions_q50": [90.0, 45.0],
            "receptions_q90": [115.0, 65.0],
            "receiving_yards_q10": [700.0, 750.0],
            "receiving_yards_q50": [1100.0, 1050.0],
            "receiving_yards_q90": [1450.0, 1400.0],
            "receiving_tds_q10": [3.0, 4.0],
            "receiving_tds_q50": [7.0, 7.0],
            "receiving_tds_q90": [12.0, 11.0],
            "fumbles_lost_q10": [0.0, 0.0],
            "fumbles_lost_q50": [0.0, 0.0],
            "fumbles_lost_q90": [0.0, 0.0],
            "two_point_conversions_q10": [0.0, 0.0],
            "two_point_conversions_q50": [0.0, 0.0],
            "two_point_conversions_q90": [0.0, 0.0],
        }
    )


def test_component_quantiles_are_rescored_before_league_value() -> None:
    frame = _receiver_frame()
    standard = value_players(
        frame,
        LeagueConfig(teams=1, scoring="standard", roster_slots={"WR": 1}),
    ).set_index("player_id")
    ppr = value_players(
        frame,
        LeagueConfig(teams=1, scoring="ppr", roster_slots={"WR": 1}),
    ).set_index("player_id")

    assert standard.loc["wr1", "league_scoring_source"] == "component_quantile_rescore"
    assert bool(standard.loc["wr1", "league_scoring_exact"]) is False
    assert bool(standard.loc["wr1", "league_scoring_approximate"]) is True
    assert ppr.loc["wr1", "valuation_points_q50"] > standard.loc["wr1", "valuation_points_q50"]
    assert (
        ppr.loc["wr1", "valuation_points_q50"] - standard.loc["wr1", "valuation_points_q50"]
    ) == 90.0
    assert ppr.loc["wr1", "vorp"] > standard.loc["wr1", "vorp"]


def test_generic_points_fallback_is_explicit() -> None:
    frame = _receiver_frame()[
        [
            "player_id",
            "player_name",
            "position",
            "season_points_q10",
            "season_points_q50",
            "season_points_q90",
        ]
    ]
    scored = prepare_league_scoring_quantiles(frame, LeagueConfig(scoring="ppr"))
    assert scored["league_scoring_fallback"].all()
    assert set(scored["league_scoring_source"]) == {"generic_points_fallback"}
    assert scored["valuation_points_q50"].tolist() == frame["season_points_q50"].tolist()


def test_provided_league_quantiles_take_priority_but_are_unverified_by_default() -> None:
    frame = _receiver_frame()
    frame["league_season_points_q10"] = [101.0, 91.0]
    frame["league_season_points_q50"] = [201.0, 181.0]
    frame["league_season_points_q90"] = [301.0, 281.0]
    scored = prepare_league_scoring_quantiles(frame, LeagueConfig(scoring="ppr"))
    assert set(scored["league_scoring_source"]) == {"provided_league_quantiles_unverified"}
    assert not scored["league_scoring_exact"].any()
    assert scored["valuation_points_q50"].tolist() == [201.0, 181.0]


def test_provided_league_quantiles_are_exact_only_with_explicit_producer_authority() -> None:
    frame = _receiver_frame()
    frame["league_season_points_q10"] = [101.0, 91.0]
    frame["league_season_points_q50"] = [201.0, 181.0]
    frame["league_season_points_q90"] = [301.0, 281.0]
    frame["league_scoring_exact"] = True
    scored = prepare_league_scoring_quantiles(frame, LeagueConfig(scoring="ppr"))
    assert set(scored["league_scoring_source"]) == {"verified_league_quantiles"}
    assert scored["league_scoring_exact"].all()
    assert scored["valuation_points_q50"].tolist() == [201.0, 181.0]
