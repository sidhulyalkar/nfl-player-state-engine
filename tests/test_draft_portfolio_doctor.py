from __future__ import annotations

from player_state_engine.product.draft_day_doctor import DraftDayDoctorReport
from player_state_engine.product.draft_portfolio_doctor import PortfolioAwareDraftDayDoctor


class _Doctor:
    def __init__(self, status: str = "READY") -> None:
        self.status = status

    def report(self, league_id=None):
        return DraftDayDoctorReport(
            status=self.status,
            can_open_war_room=True,
            all_requested_leagues_usable=True,
            checks=(),
            leagues=(),
            blocking_reasons=(),
            provisional_reasons=(),
            checked_at_utc="2026-08-31T22:00:00+00:00",
        )


class _Expectations:
    def __init__(self, value):
        self.value = value

    def expected_count(self):
        return self.value


class _DraftService:
    def __init__(self, league_ids):
        self.league_ids = league_ids

    def list_leagues(self):
        return [{"league_id": league_id, "platform": "sleeper"} for league_id in self.league_ids]


def test_undeclared_portfolio_prevents_aggregate_ready() -> None:
    service = PortfolioAwareDraftDayDoctor(
        _Doctor("READY"),
        draft_service=_DraftService(["1"]),
        expectation_store=_Expectations(None),
    )

    report = service.report()

    assert report.status == "PROVISIONAL"
    assert report.can_open_war_room is True
    assert report.all_requested_leagues_usable is False
    assert "EXPECTED_LEAGUE_PORTFOLIO_UNDECLARED" in report.provisional_reasons


def test_missing_intended_league_blocks_aggregate_only() -> None:
    service = PortfolioAwareDraftDayDoctor(
        _Doctor("READY"),
        draft_service=_DraftService(["1", "2"]),
        expectation_store=_Expectations(3),
    )

    aggregate = service.report()
    single = service.report("1")

    assert aggregate.status == "BLOCKED"
    assert aggregate.can_open_war_room is True
    assert aggregate.all_requested_leagues_usable is False
    assert "EXPECTED_LEAGUES_MISSING" in aggregate.blocking_reasons
    assert single.status == "READY"


def test_complete_expected_portfolio_preserves_scientific_provisional_status() -> None:
    service = PortfolioAwareDraftDayDoctor(
        _Doctor("PROVISIONAL"),
        draft_service=_DraftService(["1", "2", "3"]),
        expectation_store=_Expectations(3),
    )

    report = service.report()

    assert report.status == "PROVISIONAL"
    assert report.all_requested_leagues_usable is True
    assert any(check.code == "EXPECTED_LEAGUE_PORTFOLIO_CONNECTED" for check in report.checks)
