from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.product.draft_day_doctor import DraftDayDoctorService
from player_state_engine.product.projection_artifact_source import ProjectionArtifactSnapshot
from player_state_engine.product.schemas import (
    FantasyRoster,
    LeagueIdentity,
    LeagueSettings,
    LeagueSnapshot,
)


class _Source:
    def __init__(self, frame: pd.DataFrame, *, production: bool = True) -> None:
        self.frame = frame
        self.production = production

    def load(self) -> ProjectionArtifactSnapshot:
        return ProjectionArtifactSnapshot(
            frame=self.frame,
            path=__file__,
            source_mode="champion" if self.production else "path",
            authority="production_approved" if self.production else "path_unverified",
            integrity_verified=self.production,
            target="preseason_multicontract_player_values_2026" if self.production else None,
            bundle_id="bundle-1" if self.production else None,
            model_id="model-1" if self.production else None,
            code_sha="abc123" if self.production else None,
            source_cutoff_utc=datetime.now(UTC).isoformat(),
        )


class _DraftService:
    def __init__(self, snapshot: LeagueSnapshot, *, market: dict[str, object]) -> None:
        self.snapshot = snapshot
        self.market = market

    def list_leagues(self) -> list[dict[str, object]]:
        return [{"league_id": self.snapshot.identity.league_id}]

    def load_snapshot(self, league_id: str) -> LeagueSnapshot:
        if league_id != self.snapshot.identity.league_id:
            raise FileNotFoundError(league_id)
        return self.snapshot

    def market_status(self) -> dict[str, object]:
        return dict(self.market)

    def _market_status_for_league(self, league_id: str) -> dict[str, object]:
        assert league_id == self.snapshot.identity.league_id
        return dict(self.market)


def _snapshot(*, median: bool = False) -> LeagueSnapshot:
    return LeagueSnapshot(
        identity=LeagueIdentity(
            league_id="league-1",
            platform="espn",
            name="Test League",
            season=2026,
            imported_at=datetime.now(UTC),
        ),
        settings=LeagueSettings(
            teams=12,
            season=2026,
            scoring={"REC": 1.0},
            roster_positions=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN"],
            median_scoring=median,
        ),
        rosters=[FantasyRoster(roster_id="1", team_name="My Team")],
    )


def _hub() -> dict[str, object]:
    return {
        "authority": "observational_nfl_state_only",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "required_source_failures": [],
        "status": "READY",
        "market_identity": {
            "redraft_identity_coverage": 0.95,
            "usable_market_players": 500,
        },
    }


def _ready_market() -> dict[str, object]:
    return {
        "available": True,
        "expired": False,
        "stale": False,
        "age_seconds": 120.0,
        "rows": 900,
        "requested_scoring": "PPR",
        "requested_scope": "ALL",
        "format_authority": "scoring_matched_1qb_market",
        "coverage_rate": 0.9,
    }


def _patch_release_semantics(monkeypatch, config: LeagueConfig, *, market_only=()) -> None:
    import player_state_engine.product.draft_day_doctor as doctor

    monkeypatch.setattr(doctor, "load_nfl_hub_snapshot", lambda _root: _hub())
    monkeypatch.setattr(doctor, "league_config_from_snapshot", lambda _snapshot: config)
    monkeypatch.setattr(doctor, "_core_config", lambda value: value)
    monkeypatch.setattr(
        doctor,
        "assess_league_readiness",
        lambda _frame, _config: SimpleNamespace(ready=True, blocking_flags=(), score=100.0),
    )
    monkeypatch.setattr(doctor, "_required_market_only_positions", lambda _report: market_only)
    monkeypatch.setattr(
        doctor,
        "_special_teams_support",
        lambda _snapshot, now, max_age_hours: tuple(market_only),
    )


def test_doctor_can_be_fully_ready(monkeypatch, tmp_path) -> None:
    snapshot = _snapshot()
    config = LeagueConfig(
        teams=12,
        scoring="ppr",
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 1},
    )
    _patch_release_semantics(monkeypatch, config)
    frame = pd.DataFrame([{"scoring_contract_id": config.scoring_contract_id}])
    service = DraftDayDoctorService(
        projection_source=_Source(frame),
        draft_service=_DraftService(snapshot, market=_ready_market()),
        nfl_hub_root=tmp_path,
        special_teams_path=tmp_path / "special.json",
    )

    report = service.report()

    assert report.status == "READY"
    assert report.can_open_war_room is True
    assert report.all_requested_leagues_usable is True
    assert report.leagues[0].status == "READY"
    assert report.blocking_reasons == ()


def test_missing_live_adp_is_provisional_not_blocking(monkeypatch, tmp_path) -> None:
    snapshot = _snapshot()
    config = LeagueConfig(teams=12, scoring="ppr")
    _patch_release_semantics(monkeypatch, config)
    frame = pd.DataFrame([{"scoring_contract_id": config.scoring_contract_id}])
    market = {"available": False, "reason": "live_adp_snapshot_missing"}
    service = DraftDayDoctorService(
        projection_source=_Source(frame),
        draft_service=_DraftService(snapshot, market=market),
        nfl_hub_root=tmp_path,
        special_teams_path=tmp_path / "special.json",
    )

    report = service.report("league-1")

    assert report.status == "PROVISIONAL"
    assert report.can_open_war_room is True
    assert "LIVE_ADP_UNAVAILABLE" in report.provisional_reasons
    assert "LEAGUE_ADP_TIMING_UNAVAILABLE" in report.provisional_reasons


def test_special_teams_gap_blocks_only_when_league_requires_it(monkeypatch, tmp_path) -> None:
    import player_state_engine.product.draft_day_doctor as doctor

    snapshot = _snapshot()
    config = LeagueConfig(
        teams=12,
        scoring="ppr",
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1},
    )
    _patch_release_semantics(monkeypatch, config, market_only=("K", "DST"))
    monkeypatch.setattr(doctor, "_special_teams_support", lambda *_args, **_kwargs: ())
    frame = pd.DataFrame([{"scoring_contract_id": config.scoring_contract_id}])
    service = DraftDayDoctorService(
        projection_source=_Source(frame),
        draft_service=_DraftService(snapshot, market=_ready_market()),
        nfl_hub_root=tmp_path,
        special_teams_path=tmp_path / "missing.json",
    )

    report = service.report()

    assert report.status == "BLOCKED"
    assert report.can_open_war_room is False
    assert "SPECIAL_TEAMS_MARKET_SUPPORT_MISSING" in report.blocking_reasons


def test_unverified_projection_path_is_hard_blocker(monkeypatch, tmp_path) -> None:
    snapshot = _snapshot()
    config = LeagueConfig(teams=12, scoring="ppr")
    _patch_release_semantics(monkeypatch, config)
    frame = pd.DataFrame([{"scoring_contract_id": config.scoring_contract_id}])
    service = DraftDayDoctorService(
        projection_source=_Source(frame, production=False),
        draft_service=_DraftService(snapshot, market=_ready_market()),
        nfl_hub_root=tmp_path,
        special_teams_path=tmp_path / "special.json",
    )

    report = service.report()

    assert report.status == "BLOCKED"
    assert report.can_open_war_room is False
    assert "PROJECTION_AUTHORITY_NOT_PRODUCTION" in report.blocking_reasons
