from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import assess_league_readiness


def _exact_core() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for player_id, position, adp in (
        ("QB1", "QB", 10.0),
        ("RB1", "RB", 8.0),
        ("WR1", "WR", 9.0),
        ("TE1", "TE", 30.0),
    ):
        rows.append(
            {
                "player_id": player_id,
                "player_name": player_id,
                "position": position,
                "market_adp": adp,
                "league_season_points_q10": 100.0,
                "league_season_points_q50": 150.0,
                "league_season_points_q90": 220.0,
                "season_points_q10": 100.0,
                "season_points_q50": 150.0,
                "season_points_q90": 220.0,
            }
        )
    return pd.DataFrame(rows)


def test_median_game_format_is_not_labelled_exactly_ready_from_player_season_values() -> None:
    config = LeagueConfig(
        teams=12,
        scoring="half_ppr",
        median_scoring=True,
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1},
    )

    report = assess_league_readiness(_exact_core(), config)

    assert report.ready is False
    assert "MEDIAN_SCORING_POLICY_UNVALIDATED" in report.flags
    assert "MEDIAN_SCORING_POLICY_UNVALIDATED" in report.blocking_flags
    assert report.exact_scoring_coverage == 1.0


def test_identical_nonmedian_contract_does_not_receive_median_policy_blocker() -> None:
    config = LeagueConfig(
        teams=12,
        scoring="half_ppr",
        median_scoring=False,
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1},
    )

    report = assess_league_readiness(_exact_core(), config)

    assert "MEDIAN_SCORING_POLICY_UNVALIDATED" not in report.flags
    assert "MEDIAN_SCORING_POLICY_UNVALIDATED" not in report.blocking_flags
