from __future__ import annotations

from typing import Any


class DoctorDraftServiceAdapter:
    """Exception-safe read facade over the live draft service for readiness diagnosis.

    Champion/model authority is diagnosed separately by ``DraftDayDoctorService``. A failure while
    reading the optional market overlay must therefore be represented as unavailable timing evidence,
    not escape as an exception and hide the more important hard-authority finding.
    """

    def __init__(self, service: Any) -> None:
        self.service = service

    def list_leagues(self) -> list[dict[str, object]]:
        return self.service.list_leagues()

    def load_snapshot(self, league_id: str):
        return self.service.load_snapshot(league_id)

    def market_status(self) -> dict[str, object]:
        try:
            return dict(self.service.market_status())
        except Exception as exc:  # noqa: BLE001 - diagnosis must survive optional market failures.
            return {
                "available": False,
                "authority": "unavailable",
                "reason": "market_diagnostic_unavailable",
                "error": str(exc),
            }

    def _market_status_for_league(self, league_id: str) -> dict[str, object]:
        try:
            return dict(self.service._market_status_for_league(league_id))
        except Exception as exc:  # noqa: BLE001 - same fail-soft market boundary as global status.
            return {
                "available": False,
                "authority": "unavailable",
                "reason": "league_market_diagnostic_unavailable",
                "league_id": str(league_id),
                "error": str(exc),
            }
