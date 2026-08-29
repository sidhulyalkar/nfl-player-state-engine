from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.product.release_readiness import assess_sept1_release_readiness

NOW = datetime(2026, 9, 1, 16, 0, tzinfo=UTC)


def _exact_players() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": "QB1",
                "position": "QB",
                "league_season_points_q10": 220.0,
                "league_season_points_q50": 280.0,
                "league_season_points_q90": 340.0,
                "market_adp": 12.0,
            },
            {
                "player_id": "RB1",
                "position": "RB",
                "league_season_points_q10": 150.0,
                "league_season_points_q50": 220.0,
                "league_season_points_q90": 290.0,
                "market_adp": 8.0,
            },
            {
                "player_id": "WR1",
                "position": "WR",
                "league_season_points_q10": 145.0,
                "league_season_points_q50": 215.0,
                "league_season_points_q90": 300.0,
                "market_adp": 10.0,
            },
            {
                "player_id": "TE1",
                "position": "TE",
                "league_season_points_q10": 90.0,
                "league_season_points_q50": 155.0,
                "league_season_points_q90": 230.0,
                "market_adp": 35.0,
            },
        ]
    )


def _hub(*, status: str = "READY", generated_at: datetime | None = None) -> dict[str, object]:
    return {
        "authority": "observational_nfl_state_only",
        "status": status,
        "generated_at_utc": (generated_at or (NOW - timedelta(hours=1))).isoformat(),
        "player_count": 2930,
        "required_source_failures": [],
        "optional_source_failures": [] if status == "READY" else ["injuries"],
        "market_identity": {
            "redraft_identity_coverage": 0.90,
            "usable_market_players": 1100,
        },
    }


def _assess(
    projections: pd.DataFrame,
    leagues: dict[str, LeagueConfig],
    **overrides: object,
):
    kwargs: dict[str, object] = {
        "package_version": "0.17.0",
        "projection_authority": "production_approved",
        "projection_integrity_verified": True,
        "projection_source_cutoff_utc": NOW - timedelta(hours=2),
        "nfl_hub_snapshot": _hub(),
        "now": NOW,
    }
    kwargs.update(overrides)
    return assess_sept1_release_readiness(projections, leagues, **kwargs)  # type: ignore[arg-type]


def test_exact_skill_position_release_can_be_ready() -> None:
    report = _assess(_exact_players(), {"core": LeagueConfig()})

    assert report.status == "READY"
    assert report.can_use_core_draft_board is True
    assert report.blocking_reasons == ()
    assert report.provisional_reasons == ()
    assert report.leagues[0].status == "READY"


def test_missing_kicker_and_defense_are_only_provisional_when_explicitly_isolated() -> None:
    config = LeagueConfig(
        teams=8,
        scoring="ppr",
        roster_slots={
            "QB": 2,
            "RB": 3,
            "WR": 3,
            "TE": 1,
            "FLEX": 3,
            "DST": 1,
            "K": 1,
            "BENCH": 6,
        },
    )
    report = _assess(_exact_players(), {"expanded": config})

    assert report.status == "PROVISIONAL"
    assert report.can_use_core_draft_board is True
    league = report.leagues[0]
    assert league.status == "PROVISIONAL"
    assert league.market_only_positions == ("DST", "K")
    assert "MISSING_REQUIRED_POSITIONS" in league.readiness.blocking_flags
    assert "INEXACT_REQUIRED_POSITION_SCORING" in league.readiness.blocking_flags


def test_market_only_exception_can_never_hide_inexact_skill_position_scoring() -> None:
    frame = _exact_players().drop(
        columns=[
            "league_season_points_q10",
            "league_season_points_q50",
            "league_season_points_q90",
        ]
    )
    frame["season_points_q10"] = [220.0, 150.0, 145.0, 90.0]
    frame["season_points_q50"] = [280.0, 220.0, 215.0, 155.0]
    frame["season_points_q90"] = [340.0, 290.0, 300.0, 230.0]
    config = LeagueConfig(
        teams=8,
        roster_slots={"QB": 2, "RB": 3, "WR": 3, "TE": 1, "FLEX": 3, "DST": 1, "K": 1},
    )

    report = _assess(frame, {"expanded": config})

    assert report.status == "BLOCKED"
    assert report.can_use_core_draft_board is False
    assert set(report.leagues[0].readiness.inexact_required_positions) >= {"QB", "RB", "WR", "TE"}


def test_unverified_or_unapproved_projection_bundle_is_blocked() -> None:
    report = _assess(
        _exact_players(),
        {"core": LeagueConfig()},
        projection_authority="challenger",
        projection_integrity_verified=False,
    )

    assert report.status == "BLOCKED"
    assert "PROJECTION_BUNDLE_NOT_PRODUCTION_APPROVED" in report.blocking_reasons
    assert "PROJECTION_BUNDLE_INTEGRITY_UNVERIFIED" in report.blocking_reasons


def test_stale_projection_or_hub_blocks_release() -> None:
    report = _assess(
        _exact_players(),
        {"core": LeagueConfig()},
        projection_source_cutoff_utc=NOW - timedelta(hours=60),
        nfl_hub_snapshot=_hub(generated_at=NOW - timedelta(hours=20)),
    )

    assert report.status == "BLOCKED"
    assert "PROJECTION_SOURCE_CUTOFF_STALE" in report.blocking_reasons
    assert "NFL_HUB_STALE" in report.blocking_reasons


def test_low_market_identity_coverage_blocks_even_when_source_endpoint_is_up() -> None:
    hub = _hub()
    hub["market_identity"] = {
        "redraft_identity_coverage": 0.25,
        "usable_market_players": 80,
    }
    report = _assess(
        _exact_players(),
        {"core": LeagueConfig()},
        nfl_hub_snapshot=hub,
    )

    assert report.status == "BLOCKED"
    assert "NFL_HUB_MARKET_IDENTITY_COVERAGE_LOW" in report.blocking_reasons
    assert "NFL_HUB_MARKET_PLAYER_COVERAGE_LOW" in report.blocking_reasons


def test_optional_hub_degradation_is_provisional_not_silently_ready() -> None:
    report = _assess(
        _exact_players(),
        {"core": LeagueConfig()},
        nfl_hub_snapshot=_hub(status="DEGRADED"),
    )

    assert report.status == "PROVISIONAL"
    assert report.can_use_core_draft_board is True
    assert "NFL_HUB_OPTIONAL_SOURCE_DEGRADED" in report.provisional_reasons


def test_release_version_must_be_frozen_to_v017() -> None:
    report = _assess(
        _exact_players(),
        {"core": LeagueConfig()},
        package_version="0.16.0",
    )

    assert report.status == "BLOCKED"
    assert "RELEASE_VERSION_NOT_FROZEN" in report.blocking_reasons
