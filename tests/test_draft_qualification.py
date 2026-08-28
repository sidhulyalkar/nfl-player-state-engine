from __future__ import annotations

from pathlib import Path

import pytest

from player_state_engine.fantasy.draft_qualification import qualify_live_draft
from player_state_engine.fantasy.readiness import LeagueReadinessReport

ROOT = Path(__file__).resolve().parents[1]


def _readiness(
    *,
    ready: bool = True,
    flags: tuple[str, ...] = (),
    blockers: tuple[str, ...] = (),
) -> LeagueReadinessReport:
    return LeagueReadinessReport(
        score=92.0,
        ready=ready,
        flags=flags,
        blocking_flags=blockers,
        required_positions=("QB", "RB", "TE", "WR"),
        present_positions=("QB", "RB", "TE", "WR"),
        missing_positions=(),
        projection_rows=220,
        unique_player_coverage=1.0,
        market_adp_coverage=0.94,
        market_coverage=0.94,
        market_source="market_adp",
        exact_scoring_coverage=1.0,
        valuation_coverage=1.0,
    )


def _qualify(readiness: LeagueReadinessReport, **overrides: object):
    kwargs: dict[str, object] = {
        "projection_age_hours": 2.0,
        "max_projection_age_hours": 24.0,
        "snapshot_age_seconds": 10.0,
        "stale_after_seconds": 60.0,
        "refresh_warning": None,
    }
    kwargs.update(overrides)
    return qualify_live_draft(readiness, **kwargs)  # type: ignore[arg-type]


def test_clean_live_draft_is_ready() -> None:
    report = _qualify(_readiness())
    assert report.status == "READY"
    assert report.can_act is True
    assert report.blocking_reasons == ()
    assert report.caution_reasons == ()
    assert report.projection_fresh is True
    assert report.live_snapshot_fresh is True


def test_nonblocking_readiness_flag_becomes_caution() -> None:
    report = _qualify(_readiness(flags=("LOW_MARKET_COVERAGE",)))
    assert report.status == "CAUTION"
    assert report.can_act is True
    assert report.caution_reasons == ("LOW_MARKET_COVERAGE",)


def test_stale_projection_blocks_action() -> None:
    report = _qualify(_readiness(), projection_age_hours=48.0)
    assert report.status == "BLOCKED"
    assert report.can_act is False
    assert "STALE_PROJECTIONS" in report.blocking_reasons
    assert report.projection_fresh is False


def test_missing_projection_artifact_blocks_action() -> None:
    report = _qualify(_readiness(), projection_age_hours=None)
    assert report.status == "BLOCKED"
    assert report.can_act is False
    assert "PROJECTION_ARTIFACT_UNAVAILABLE" in report.blocking_reasons


def test_stale_live_snapshot_blocks_action() -> None:
    report = _qualify(_readiness(), snapshot_age_seconds=61.0)
    assert report.status == "BLOCKED"
    assert report.can_act is False
    assert "STALE_LIVE_SNAPSHOT" in report.blocking_reasons
    assert report.live_snapshot_fresh is False


def test_refresh_warning_is_visible_without_overriding_fresh_state() -> None:
    report = _qualify(_readiness(), refresh_warning="platform refresh returned cached data")
    assert report.status == "CAUTION"
    assert report.can_act is True
    assert report.refresh_healthy is False
    assert "LIVE_REFRESH_WARNING" in report.caution_reasons


def test_existing_league_blocker_remains_authoritative() -> None:
    report = _qualify(
        _readiness(
            ready=False,
            flags=("MISSING_REQUIRED_POSITIONS",),
            blockers=("MISSING_REQUIRED_POSITIONS",),
        )
    )
    assert report.status == "BLOCKED"
    assert report.can_act is False
    assert report.blocking_reasons == ("MISSING_REQUIRED_POSITIONS",)


def test_invalid_freshness_thresholds_fail_closed() -> None:
    with pytest.raises(ValueError, match="max_projection_age_hours"):
        _qualify(_readiness(), max_projection_age_hours=0.0)
    with pytest.raises(ValueError, match="snapshot_age_seconds"):
        _qualify(_readiness(), snapshot_age_seconds=-1.0)
    with pytest.raises(ValueError, match="stale_after_seconds"):
        _qualify(_readiness(), stale_after_seconds=0.0)


def test_weekly_refresh_installs_dependencies_required_by_its_full_test_suite() -> None:
    workflow = (ROOT / ".github" / "workflows" / "weekly_model_refresh.yml").read_text(
        encoding="utf-8"
    )
    assert 'pip install -e ".[dev,intelligence,api]"' in workflow
