from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import player_state_engine.product.draft_launch_control as launch_module
from player_state_engine.product.draft_day_doctor import DraftDayDoctorReport
from player_state_engine.product.draft_launch_control import DraftLaunchControlService
from player_state_engine.product.schemas import FantasyRoster, LeagueIdentity, LeagueSettings, LeagueSnapshot


def _snapshot(*, roster_positions=None) -> LeagueSnapshot:
    return LeagueSnapshot(
        identity=LeagueIdentity(
            league_id="12345",
            platform="sleeper",
            name="Tomorrow League",
            season=2026,
            imported_at=datetime.now(UTC),
            external_user_id="user-1",
        ),
        settings=LeagueSettings(
            teams=8,
            season=2026,
            scoring={"rec": 1.0, "pass_td": 4.0},
            roster_positions=roster_positions or ["QB", "RB", "WR", "TE", "FLEX", "BN"],
        ),
        rosters=[FantasyRoster(roster_id=str(index), team_name=f"Team {index}") for index in range(8)],
    )


class _Doctor:
    def report(self):
        return DraftDayDoctorReport(
            status="READY",
            can_open_war_room=True,
            all_requested_leagues_usable=True,
            checks=(),
            leagues=(),
            blocking_reasons=(),
            provisional_reasons=(),
            checked_at_utc="2026-08-31T23:00:00+00:00",
        )


class _DraftService:
    def __init__(self, snapshot: LeagueSnapshot) -> None:
        self.snapshot = snapshot
        self.market_refreshes = 0

    def list_leagues(self):
        return [
            {"league_id": "demo-league", "platform": "demo", "name": "Demo"},
            {"league_id": self.snapshot.identity.league_id, "platform": "sleeper", "name": self.snapshot.identity.name},
        ]

    def load_snapshot(self, league_id: str):
        assert league_id == self.snapshot.identity.league_id
        return self.snapshot

    def market_status(self):
        return {"available": False, "reason": "missing"}

    def refresh_market(self, season: int):
        self.market_refreshes += 1
        return {"rows": 400, "captured_at_utc": "2026-08-31T23:00:00+00:00"}


class _Connections:
    def __init__(self, draft: _DraftService, *, fail: bool = False) -> None:
        self.draft = draft
        self.fail = fail
        self.calls = 0

    def connect(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("platform unavailable")
        return SimpleNamespace(league_name=self.draft.snapshot.identity.name, roster_count=8)


def _service(tmp_path, draft, connections):
    return DraftLaunchControlService(
        draft_service=draft,
        connection_service=connections,
        doctor_service=_Doctor(),
        nfl_hub_root=tmp_path / "hub",
        special_teams_path=tmp_path / "special.json",
    )


def test_prepare_refreshes_current_state_without_model_authority(monkeypatch, tmp_path) -> None:
    draft = _DraftService(_snapshot())
    connections = _Connections(draft)
    service = _service(tmp_path, draft, connections)
    monkeypatch.delenv("PSE_FANTASYPROS_API_KEY", raising=False)
    monkeypatch.setattr(
        launch_module,
        "refresh_nfl_hub",
        lambda **kwargs: {"generated_at_utc": "2026-08-31T23:00:00+00:00", "status": "READY", "authority": "observational"},
    )

    report = service.prepare(season=2026)

    assert report.status == "READY"
    assert report.can_open_war_room is True
    assert report.authority == "current_state_refresh_only"
    assert report.champion_mutated is False
    assert report.model_promotion_performed is False
    assert connections.calls == 1
    assert draft.market_refreshes == 0
    statuses = {stage.name: stage.status for stage in report.stages}
    assert statuses["nfl_hub"] == "REFRESHED"
    assert statuses["league:12345"] == "REFRESHED"
    assert statuses["special_teams_market"] == "SKIPPED"
    assert statuses["live_adp"] == "SKIPPED"


def test_failed_league_refresh_preserves_valid_snapshot(monkeypatch, tmp_path) -> None:
    draft = _DraftService(_snapshot())
    connections = _Connections(draft, fail=True)
    service = _service(tmp_path, draft, connections)
    monkeypatch.delenv("PSE_FANTASYPROS_API_KEY", raising=False)
    monkeypatch.setattr(
        launch_module,
        "refresh_nfl_hub",
        lambda **kwargs: {"generated_at_utc": "2026-08-31T23:00:00+00:00", "status": "READY", "authority": "observational"},
    )

    report = service.prepare()

    league_stage = next(stage for stage in report.stages if stage.name == "league:12345")
    assert league_stage.status == "PRESERVED"
    assert "preserved" in league_stage.detail.lower()


def test_failed_special_teams_refresh_preserves_previous_market(monkeypatch, tmp_path) -> None:
    draft = _DraftService(_snapshot(roster_positions=["QB", "RB", "WR", "K", "DST", "BN"]))
    connections = _Connections(draft)
    service = _service(tmp_path, draft, connections)
    monkeypatch.delenv("PSE_FANTASYPROS_API_KEY", raising=False)
    monkeypatch.setattr(
        launch_module,
        "refresh_nfl_hub",
        lambda **kwargs: {"generated_at_utc": "2026-08-31T23:00:00+00:00", "status": "READY", "authority": "observational"},
    )
    service.special_teams_path.write_text(
        json.dumps({"authority": "external_market_only", "generated_at_utc": "2026-08-31T20:00:00+00:00"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        launch_module,
        "refresh_special_teams_market",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("source unavailable")),
    )

    report = service.prepare()

    stage = next(stage for stage in report.stages if stage.name == "special_teams_market")
    assert stage.status == "PRESERVED"
    assert json.loads(service.special_teams_path.read_text(encoding="utf-8"))["authority"] == "external_market_only"


def test_prepare_is_single_flight(tmp_path) -> None:
    draft = _DraftService(_snapshot())
    service = _service(tmp_path, draft, _Connections(draft))
    assert service._lock.acquire(blocking=False) is True
    try:
        with pytest.raises(RuntimeError, match="already running"):
            service.prepare()
    finally:
        service._lock.release()
