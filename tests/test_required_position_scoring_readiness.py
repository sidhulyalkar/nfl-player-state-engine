from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import assess_league_readiness


def _skill_row(player_id: str, position: str, adp: float) -> dict[str, object]:
    row: dict[str, object] = {
        "player_id": player_id,
        "player_name": player_id,
        "position": position,
        "market_adp": adp,
        "season_points_q10": 100.0,
        "season_points_q50": 150.0,
        "season_points_q90": 200.0,
        # This fixture represents league points scored on correlated football draws upstream.
        "league_season_points_q10": 100.0,
        "league_season_points_q50": 150.0,
        "league_season_points_q90": 200.0,
        "league_scoring_exact": True,
    }
    required = {
        "QB": ("passing_yards", "passing_tds", "interceptions", "rushing_yards", "rushing_tds"),
        "RB": ("rushing_yards", "rushing_tds", "receptions", "receiving_yards", "receiving_tds"),
        "WR": ("receptions", "receiving_yards", "receiving_tds"),
        "TE": ("receptions", "receiving_yards", "receiving_tds"),
    }[position]
    for statistic in required:
        for quantile, value in ((10, 1.0), (50, 2.0), (90, 3.0)):
            row[f"{statistic}_q{quantile}"] = value
    return row


def _league() -> LeagueConfig:
    return LeagueConfig(
        teams=8,
        scoring="ppr",
        roster_slots={
            "QB": 2,
            "RB": 3,
            "WR": 3,
            "TE": 1,
            "FLEX": 3,
            "DEF": 1,
            "K": 1,
            "BENCH": 6,
        },
    )


def test_large_skill_population_cannot_hide_generic_kicker_and_dst_scoring() -> None:
    rows: list[dict[str, object]] = []
    adp = 1.0
    for position in ("QB", "RB", "WR", "TE"):
        for index in range(30):
            rows.append(_skill_row(f"{position}-{index}", position, adp))
            adp += 1.0
    # Generic season-points rows make these positions present and fully valued, but they are not
    # exact league rescoring. A large population of explicitly exact skill rows must never dilute
    # these two entirely approximate required positions into a READY league contract.
    rows.extend(
        [
            {
                "player_id": "DST-1",
                "player_name": "DST-1",
                "position": "DEF",
                "market_adp": adp,
                "season_points_q10": 80.0,
                "season_points_q50": 100.0,
                "season_points_q90": 120.0,
            },
            {
                "player_id": "K-1",
                "player_name": "K-1",
                "position": "K",
                "market_adp": adp + 1.0,
                "season_points_q10": 90.0,
                "season_points_q50": 110.0,
                "season_points_q90": 130.0,
            },
        ]
    )
    frame = pd.DataFrame(rows).replace({np.nan: None})
    report = assess_league_readiness(frame, _league())

    assert report.exact_scoring_coverage > 0.95
    assert report.missing_positions == ()
    assert report.valuation_coverage == 1.0
    assert report.required_position_exact_scoring["DST"] == 0.0
    assert report.required_position_exact_scoring["K"] == 0.0
    assert set(report.inexact_required_positions) == {"DST", "K"}
    assert "INEXACT_REQUIRED_POSITION_SCORING" in report.blocking_flags
    assert report.ready is False


def test_exact_required_skill_positions_remain_ready_when_contract_has_no_k_dst() -> None:
    rows = [
        _skill_row("QB-1", "QB", 1.0),
        _skill_row("RB-1", "RB", 2.0),
        _skill_row("WR-1", "WR", 3.0),
        _skill_row("TE-1", "TE", 4.0),
    ]
    league = LeagueConfig(
        teams=8,
        scoring="ppr",
        roster_slots={"QB": 1, "RB": 1, "WR": 1, "TE": 1, "BENCH": 2},
    )
    report = assess_league_readiness(pd.DataFrame(rows), league)
    assert report.inexact_required_positions == ()
    assert all(value == 1.0 for value in report.required_position_exact_scoring.values())
    assert report.ready is True


def test_required_position_scoring_threshold_is_validated() -> None:
    league = LeagueConfig(teams=8, scoring="ppr", roster_slots={"QB": 1})
    with np.testing.assert_raises(ValueError):
        assess_league_readiness(
            pd.DataFrame([_skill_row("QB-1", "QB", 1.0)]),
            league,
            minimum_required_position_exact_scoring_coverage=1.1,
        )
