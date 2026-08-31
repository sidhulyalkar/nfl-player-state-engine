from __future__ import annotations

from player_state_engine.product.draft_day_doctor_adapter import DoctorDraftServiceAdapter


class _BrokenMarketService:
    def list_leagues(self):
        return [{"league_id": "league-1"}]

    def load_snapshot(self, league_id: str):
        return {"league_id": league_id}

    def market_status(self):
        raise RuntimeError("market root unreadable")

    def _market_status_for_league(self, league_id: str):
        raise FileNotFoundError(f"projection path unavailable for {league_id}")


def test_adapter_preserves_non_market_diagnostics() -> None:
    adapter = DoctorDraftServiceAdapter(_BrokenMarketService())

    assert adapter.list_leagues() == [{"league_id": "league-1"}]
    assert adapter.load_snapshot("league-1") == {"league_id": "league-1"}


def test_adapter_turns_global_market_failure_into_unavailable_evidence() -> None:
    status = DoctorDraftServiceAdapter(_BrokenMarketService()).market_status()

    assert status["available"] is False
    assert status["authority"] == "unavailable"
    assert status["reason"] == "market_diagnostic_unavailable"
    assert "market root unreadable" in str(status["error"])


def test_adapter_turns_league_market_failure_into_unavailable_evidence() -> None:
    status = DoctorDraftServiceAdapter(_BrokenMarketService())._market_status_for_league("league-1")

    assert status["available"] is False
    assert status["authority"] == "unavailable"
    assert status["reason"] == "league_market_diagnostic_unavailable"
    assert status["league_id"] == "league-1"
    assert "projection path unavailable" in str(status["error"])
