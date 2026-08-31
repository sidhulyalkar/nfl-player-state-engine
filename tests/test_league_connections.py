from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from player_state_engine.api.league_connection_routes import LeagueConnectionRequest
from player_state_engine.product.draft_day_doctor_adapter import (
    DoctorDraftServiceAdapter,
    is_real_league_summary,
)
from player_state_engine.product.league_connections import (
    LeagueConnectionService,
    LeaguePortfolioExpectationStore,
)
from player_state_engine.product.schemas import (
    FantasyRoster,
    LeagueIdentity,
    LeagueSettings,
    LeagueSnapshot,
)
from player_state_engine.product.store import LeagueSnapshotStore


def _snapshot(
    *,
    league_id: str = "12345",
    platform: str = "sleeper",
    season: int = 2026,
    name: str = "Real League",
) -> LeagueSnapshot:
    return LeagueSnapshot(
        identity=LeagueIdentity(
            league_id=league_id,
            platform=platform,
            name=name,
            season=season,
            imported_at=datetime.now(UTC),
        ),
        settings=LeagueSettings(
            teams=8,
            season=season,
            scoring={"rec": 1.0, "pass_td": 4.0},
            roster_positions=["QB", "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN"],
        ),
        rosters=[FantasyRoster(roster_id=str(index), team_name=f"Team {index}") for index in range(8)],
    )


class _Sleeper:
    def __init__(self, snapshot: LeagueSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[dict[str, object]] = []

    def import_league(self, league_id: str, **kwargs):
        self.calls.append({"league_id": league_id, **kwargs})
        return self.snapshot


class _Espn:
    def __init__(self, snapshot: LeagueSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[dict[str, object]] = []

    def import_league(self, league_id: str, **kwargs):
        self.calls.append({"league_id": league_id, **kwargs})
        return self.snapshot


def test_connect_sleeper_validates_then_atomically_persists(tmp_path) -> None:
    store = LeagueSnapshotStore(tmp_path / "leagues")
    sleeper = _Sleeper(_snapshot())
    service = LeagueConnectionService(store=store, sleeper=sleeper, espn=_Espn(_snapshot(platform="espn")))

    result = service.connect(
        platform="sleeper",
        league_id="12345",
        season=2026,
        external_user_id="user-7",
    )

    assert result.league_id == "12345"
    assert result.roster_count == 8
    assert store.load("12345").identity.name == "Real League"
    assert not list((tmp_path / "leagues").glob("*.next"))
    assert sleeper.calls[0]["external_user_id"] == "user-7"


def test_invalid_import_never_overwrites_prior_valid_snapshot(tmp_path) -> None:
    store = LeagueSnapshotStore(tmp_path / "leagues")
    prior = _snapshot(name="Prior Valid")
    store.save(prior)
    invalid = _snapshot(season=2025, name="Wrong Season")
    service = LeagueConnectionService(store=store, sleeper=_Sleeper(invalid), espn=_Espn(invalid))

    with pytest.raises(ValueError, match="season mismatch"):
        service.connect(platform="sleeper", league_id="12345", season=2026)

    assert store.load("12345").identity.name == "Prior Valid"


def test_browser_connection_schema_forbids_espn_cookie_fields() -> None:
    with pytest.raises(ValidationError):
        LeagueConnectionRequest.model_validate(
            {
                "platform": "espn",
                "league_id": "1427420",
                "season": 2026,
                "espn_s2": "must-not-cross-browser-boundary",
                "swid": "also-forbidden",
            }
        )


def test_portfolio_expectation_store_is_local_and_atomic(tmp_path) -> None:
    path = tmp_path / "league_portfolio.json"
    store = LeaguePortfolioExpectationStore(path)

    assert store.expected_count() is None
    saved = store.save_expected_count(3)

    assert saved == path
    assert store.expected_count() == 3
    assert not path.with_suffix(".json.next").exists()


def test_demo_snapshots_do_not_count_as_real_leagues() -> None:
    assert is_real_league_summary({"league_id": "demo-league", "platform": "demo"}) is False
    assert is_real_league_summary({"league_id": "123", "platform": "sleeper"}) is True
    assert is_real_league_summary({"league_id": "456", "platform": "espn"}) is True


class _ListService:
    def list_leagues(self):
        return [
            {"league_id": "demo-league", "platform": "demo"},
            {"league_id": "123", "platform": "sleeper"},
        ]


def test_doctor_adapter_excludes_showcase_leagues_from_aggregate() -> None:
    adapter = DoctorDraftServiceAdapter(_ListService())

    assert adapter.list_leagues() == [{"league_id": "123", "platform": "sleeper"}]
