from __future__ import annotations

from typing import Any


NON_REAL_LEAGUE_PLATFORMS = frozenset({"demo", "synthetic", "example"})


def is_real_league_summary(item: dict[str, object]) -> bool:
    platform = str(item.get("platform") or "").strip().lower()
    league_id = str(item.get("league_id") or "").strip().lower()
    if not league_id:
        return False
    if platform in NON_REAL_LEAGUE_PLATFORMS:
        return False
    return not league_id.startswith("demo-")


class DoctorDraftServiceAdapter:
    """Exception-safe read facade over the live draft service for readiness diagnosis.

    Champion/model authority is diagnosed separately by ``DraftDayDoctorService``. A failure while
    reading the optional market overlay must therefore be represented as unavailable timing evidence,
    not escape as an exception and hide the more important hard-authority finding. Aggregate draft
    readiness also excludes tracked demo/example snapshots so showcase data cannot satisfy or poison
    the operator's real-league portfolio contract.
    """

    def __init__(self, service: Any) -> None:
        self.service = service

    def list_leagues(self) -> list[dict[str, object]]:
        return [
            dict(item)
            for item in self.service.list_leagues()
            if is_real_league_summary(dict(item))
        ]

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
