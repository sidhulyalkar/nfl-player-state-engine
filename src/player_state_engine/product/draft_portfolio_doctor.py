from __future__ import annotations

from dataclasses import replace
from typing import Any

from player_state_engine.product.draft_day_doctor import (
    DoctorCheck,
    DraftDayDoctorReport,
    DraftDayDoctorService,
)
from player_state_engine.product.league_connections import LeaguePortfolioExpectationStore


class PortfolioAwareDraftDayDoctor:
    """Add intended-league completeness to the existing authority diagnosis.

    A missing second/third league must not masquerade as a complete portfolio merely because every
    currently installed snapshot is healthy. At the same time, portfolio incompleteness does not
    revoke the core authority of an already connected league, so ``can_open_war_room`` is preserved.
    """

    def __init__(
        self,
        doctor: DraftDayDoctorService,
        *,
        draft_service: Any,
        expectation_store: LeaguePortfolioExpectationStore | None = None,
    ) -> None:
        self.doctor = doctor
        self.draft_service = draft_service
        self.expectation_store = expectation_store or LeaguePortfolioExpectationStore()

    def report(self, league_id: str | None = None) -> DraftDayDoctorReport:
        base = self.doctor.report(league_id=league_id)
        # A one-league query answers whether that league itself is usable. Portfolio completeness is
        # an all-leagues operator contract and is intentionally applied only to the aggregate report.
        if league_id is not None:
            return base

        expected = self.expectation_store.expected_count()
        if expected is None:
            check = DoctorCheck(
                code="EXPECTED_LEAGUE_PORTFOLIO_UNDECLARED",
                status="PROVISIONAL",
                detail=(
                    "The intended number of real draft leagues has not been declared, so aggregate "
                    "portfolio completeness cannot be certified."
                ),
                remediation="Set the intended league count in the Draft Room connector.",
            )
            status = "BLOCKED" if base.status == "BLOCKED" else "PROVISIONAL"
            return replace(
                base,
                status=status,
                all_requested_leagues_usable=False,
                checks=(*base.checks, check),
                provisional_reasons=tuple(
                    dict.fromkeys((*base.provisional_reasons, check.code))
                ),
            )

        try:
            summaries = self.draft_service.list_leagues()
            connected_ids = {
                str(item.get("league_id"))
                for item in summaries
                if item.get("league_id") not in {None, ""}
            }
        except Exception as exc:  # noqa: BLE001 - diagnosis should explain portfolio read failures.
            check = DoctorCheck(
                code="EXPECTED_LEAGUE_PORTFOLIO_UNREADABLE",
                status="BLOCKED",
                detail=f"Expected league portfolio could not be enumerated: {exc}",
                remediation="Repair the local league snapshot store before relying on aggregate readiness.",
            )
            return replace(
                base,
                status="BLOCKED",
                all_requested_leagues_usable=False,
                checks=(*base.checks, check),
                blocking_reasons=tuple(
                    dict.fromkeys((*base.blocking_reasons, check.code))
                ),
            )

        connected = len(connected_ids)
        if connected < expected:
            missing = expected - connected
            check = DoctorCheck(
                code="EXPECTED_LEAGUES_MISSING",
                status="BLOCKED",
                detail=(
                    f"Only {connected} of {expected} intended draft leagues are connected; "
                    f"{missing} still need real platform snapshots."
                ),
                remediation="Use the Draft Room league connector to import each remaining real league.",
                data={
                    "expected_league_count": expected,
                    "connected_league_count": connected,
                    "missing_league_count": missing,
                },
            )
            return replace(
                base,
                status="BLOCKED",
                all_requested_leagues_usable=False,
                checks=(*base.checks, check),
                blocking_reasons=tuple(
                    dict.fromkeys((*base.blocking_reasons, check.code))
                ),
            )

        check = DoctorCheck(
            code="EXPECTED_LEAGUE_PORTFOLIO_CONNECTED",
            status="READY",
            detail=f"All {expected} intended draft leagues have real installed snapshots.",
            data={
                "expected_league_count": expected,
                "connected_league_count": connected,
            },
        )
        return replace(base, checks=(*base.checks, check))
