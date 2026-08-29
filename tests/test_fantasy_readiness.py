from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import assess_league_readiness


def _core_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": "QB1",
                "position": "QB",
                "season_points_q10": 200,
                "season_points_q50": 250,
                "season_points_q90": 300,
                "market_adp": 20,
            },
            {
                "player_id": "RB1",
                "position": "RB",
                "season_points_q10": 150,
                "season_points_q50": 210,
                "season_points_q90": 270,
                "market_adp": 10,
            },
            {
                "player_id": "WR1",
                "position": "WR",
                "season_points_q10": 140,
                "season_points_q50": 205,
                "season_points_q90": 275,
                "market_adp": 11,
            },
            {
                "player_id": "TE1",
                "position": "TE",
                "season_points_q10": 100,
                "season_points_q50": 160,
                "season_points_q90": 220,
                "market_adp": 40,
            },
        ]
    )


def test_readiness_fails_loudly_when_custom_league_positions_are_absent() -> None:
    config = LeagueConfig(
        teams=8,
        roster_slots={
            "QB": 2,
            "RB": 3,
            "WR": 3,
            "TE": 1,
            "FLEX": 3,
            "DST": 1,
            "K": 1,
            "BENCH": 8,
        },
    )

    report = assess_league_readiness(_core_rows(), config)

    assert report.ready is False
    assert {"DST", "K"}.issubset(report.missing_positions)
    assert "MISSING_REQUIRED_POSITIONS" in report.blocking_flags
    assert report.required_positions == ("DST", "K", "QB", "RB", "TE", "WR")


def test_position_aliases_prevent_false_defense_and_kicker_gaps() -> None:
    frame = pd.concat(
        [
            _core_rows(),
            pd.DataFrame(
                [
                    {
                        "player_id": "DST1",
                        "position": "DEF",
                        "season_points_q10": 50,
                        "season_points_q50": 80,
                        "season_points_q90": 120,
                        "market_adp": 145,
                    },
                    {
                        "player_id": "K1",
                        "position": "PK",
                        "season_points_q10": 70,
                        "season_points_q50": 95,
                        "season_points_q90": 125,
                        "market_adp": 150,
                    },
                ]
            ),
        ],
        ignore_index=True,
    )
    config = LeagueConfig(
        teams=8,
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1},
    )

    report = assess_league_readiness(frame, config)

    assert report.missing_positions == ()
    assert {"DST", "K"}.issubset(report.present_positions)
    assert "MISSING_REQUIRED_POSITIONS" not in report.flags
    assert {"DST", "K"}.issubset(report.inexact_required_positions)
    assert "INEXACT_REQUIRED_POSITION_SCORING" in report.blocking_flags


def test_market_pick_quantile_counts_as_explicit_market_coverage() -> None:
    frame = _core_rows().drop(columns="market_adp")
    frame["market_pick_q50"] = [20.0, 10.0, 11.0, 40.0]
    report = assess_league_readiness(frame, LeagueConfig(teams=12))

    assert report.market_source == "market_pick_q50"
    assert report.market_coverage == 1.0
    assert "MISSING_MARKET_DATA" not in report.flags


def test_generic_scoring_is_visible_but_blocks_required_position_exactness() -> None:
    report = assess_league_readiness(
        _core_rows(),
        LeagueConfig(
            teams=12,
            scoring="half_ppr",
            roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1},
        ),
    )

    assert report.ready is False
    assert report.valuation_coverage == 1.0
    assert report.exact_scoring_coverage == 0.0
    assert set(report.inexact_required_positions) == {"QB", "RB", "WR", "TE"}
    assert all(value == 0.0 for value in report.required_position_exact_scoring.values())
    assert "GENERIC_SCORING_FALLBACK" in report.flags
    assert "GENERIC_SCORING_FALLBACK" not in report.blocking_flags
    assert "INEXACT_REQUIRED_POSITION_SCORING" in report.blocking_flags


def test_duplicate_and_blank_player_ids_are_hard_failures() -> None:
    frame = pd.concat([_core_rows(), _core_rows().iloc[[0]]], ignore_index=True)
    frame.loc[1, "player_id"] = ""
    report = assess_league_readiness(frame, LeagueConfig(teams=12))

    assert report.ready is False
    assert "MISSING_PLAYER_ID_VALUES" in report.blocking_flags
    assert "DUPLICATE_PLAYER_IDS" in report.blocking_flags


def test_threshold_arguments_fail_closed_when_out_of_range() -> None:
    frame = _core_rows()
    config = LeagueConfig()

    for keyword, value in (
        ("minimum_market_coverage", 1.1),
        ("minimum_exact_scoring_coverage", -0.1),
        ("minimum_valuation_coverage", 1.2),
        ("minimum_ready_score", 101.0),
        ("minimum_required_position_exact_scoring_coverage", 1.1),
    ):
        try:
            assess_league_readiness(frame, config, **{keyword: value})
        except ValueError:
            continue
        raise AssertionError(f"Expected invalid readiness threshold to fail: {keyword}={value}")
