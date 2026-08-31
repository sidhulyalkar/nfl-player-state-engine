from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from player_state_engine.fantasy.readiness import assess_league_readiness
from player_state_engine.integrations.portfolio import league_config_from_snapshot
from player_state_engine.product.nfl_hub import load_nfl_hub_snapshot
from player_state_engine.product.projection_artifact_source import ProjectionArtifactSource
from player_state_engine.product.release_readiness import (
    _core_config,
    _required_market_only_positions,
    _special_teams_support,
)

DoctorStatus = Literal["READY", "PROVISIONAL", "BLOCKED"]


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    code: str
    status: DoctorStatus
    detail: str
    remediation: str | None = None
    data: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class LeagueDoctorReport:
    league_id: str
    league_name: str
    platform: str
    status: DoctorStatus
    can_use_core_draft_board: bool
    scoring_contract_id: str | None
    checks: tuple[DoctorCheck, ...]
    blocking_reasons: tuple[str, ...]
    provisional_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DraftDayDoctorReport:
    status: DoctorStatus
    can_open_war_room: bool
    all_requested_leagues_usable: bool
    checks: tuple[DoctorCheck, ...]
    leagues: tuple[LeagueDoctorReport, ...]
    blocking_reasons: tuple[str, ...]
    provisional_reasons: tuple[str, ...]
    checked_at_utc: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_utc(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _age_hours(value: object, *, now: datetime) -> float | None:
    parsed = _parse_utc(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds() / 3600.0)


def _status(checks: list[DoctorCheck]) -> DoctorStatus:
    if any(check.status == "BLOCKED" for check in checks):
        return "BLOCKED"
    if any(check.status == "PROVISIONAL" for check in checks):
        return "PROVISIONAL"
    return "READY"


def _reason_codes(checks: list[DoctorCheck], status: DoctorStatus) -> tuple[str, ...]:
    return tuple(dict.fromkeys(check.code for check in checks if check.status == status))


def _load_json(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


class DraftDayDoctorService:
    """One operational verdict over every authority needed on the fantasy draft clock.

    This is intentionally a composition layer. It does not promote artifacts, refresh external
    sources, weaken scientific release contracts, or fabricate missing league/market state.
    """

    def __init__(
        self,
        *,
        projection_source: ProjectionArtifactSource,
        draft_service: Any,
        nfl_hub_root: str | Path | None = None,
        special_teams_path: str | Path | None = None,
    ) -> None:
        self.projection_source = projection_source
        self.draft_service = draft_service
        self.nfl_hub_root = Path(
            nfl_hub_root or os.getenv("PSE_NFL_HUB_ROOT", "data/product/nfl_hub")
        )
        self.special_teams_path = Path(
            special_teams_path
            or os.getenv(
                "PSE_SPECIAL_TEAMS_MARKET_PATH",
                "data/product/special_teams_market/current.json",
            )
        )

    @staticmethod
    def _check(
        code: str,
        status: DoctorStatus,
        detail: str,
        remediation: str | None = None,
        **data: object,
    ) -> DoctorCheck:
        return DoctorCheck(
            code=code,
            status=status,
            detail=detail,
            remediation=remediation,
            data=data or None,
        )

    def _projection_checks(
        self, *, now: datetime
    ) -> tuple[list[DoctorCheck], pd.DataFrame | None]:
        try:
            snapshot = self.projection_source.load()
        except (OSError, KeyError, ValueError, PermissionError, RuntimeError) as exc:
            return [
                self._check(
                    "PROJECTION_CHAMPION_UNAVAILABLE",
                    "BLOCKED",
                    f"Verified projection champion could not be loaded: {exc}",
                    "Materialize the reviewed production bundle and restart the Product API.",
                )
            ], None

        checks: list[DoctorCheck] = []
        if (
            snapshot.source_mode != "champion"
            or snapshot.authority != "production_approved"
            or not snapshot.integrity_verified
        ):
            checks.append(
                self._check(
                    "PROJECTION_AUTHORITY_NOT_PRODUCTION",
                    "BLOCKED",
                    "Actual-draft use requires a byte-verified production-approved champion.",
                    "Set champion-mode environment variables and activate the reviewed bundle.",
                    source_mode=snapshot.source_mode,
                    authority=snapshot.authority,
                    integrity_verified=snapshot.integrity_verified,
                )
            )
        else:
            checks.append(
                self._check(
                    "PROJECTION_CHAMPION_VERIFIED",
                    "READY",
                    f"Production champion {snapshot.bundle_id} is byte-verified.",
                    bundle_id=snapshot.bundle_id,
                    target=snapshot.target,
                    model_id=snapshot.model_id,
                    code_sha=snapshot.code_sha,
                )
            )

        age = _age_hours(snapshot.source_cutoff_utc, now=now)
        if age is None or age > 36.0:
            checks.append(
                self._check(
                    "PROJECTION_SOURCE_CUTOFF_STALE",
                    "BLOCKED",
                    "Projection source cutoff is missing or older than the 36-hour draft gate.",
                    "Run a fresh preseason candidate rehearsal and explicitly approve the new bundle.",
                    age_hours=age,
                    source_cutoff_utc=snapshot.source_cutoff_utc,
                )
            )
        else:
            checks.append(
                self._check(
                    "PROJECTION_SOURCE_CUTOFF_FRESH",
                    "READY",
                    f"Projection source cutoff is {age:.1f} hours old.",
                    age_hours=age,
                )
            )
        return checks, snapshot.frame

    def _hub_checks(self, *, now: datetime) -> list[DoctorCheck]:
        snapshot = load_nfl_hub_snapshot(self.nfl_hub_root)
        if not snapshot:
            return [
                self._check(
                    "NFL_HUB_UNAVAILABLE",
                    "BLOCKED",
                    "No current NFL Hub snapshot is installed.",
                    "Run: python scripts/refresh_nfl_hub.py --season 2026",
                )
            ]

        checks: list[DoctorCheck] = []
        age = _age_hours(snapshot.get("generated_at_utc"), now=now)
        required_failures = tuple(snapshot.get("required_source_failures") or ())
        market_identity = snapshot.get("market_identity") or {}
        if not isinstance(market_identity, dict):
            market_identity = {}
        coverage = float(market_identity.get("redraft_identity_coverage", 0.0) or 0.0)
        players = int(market_identity.get("usable_market_players", 0) or 0)

        blockers: list[str] = []
        if snapshot.get("authority") != "observational_nfl_state_only":
            blockers.append("authority")
        if age is None or age > 12.0:
            blockers.append("stale")
        if required_failures:
            blockers.append("required_source_failure")
        if str(snapshot.get("status") or "").upper() not in {"READY", "DEGRADED"}:
            blockers.append("status")
        if coverage < 0.70:
            blockers.append("market_identity_coverage")
        if players < 250:
            blockers.append("market_player_coverage")

        if blockers:
            checks.append(
                self._check(
                    "NFL_HUB_NOT_DRAFT_READY",
                    "BLOCKED",
                    "NFL Hub violates one or more hard draft-data contracts: " + ", ".join(blockers),
                    "Refresh the NFL Hub and repair required-source or identity-coverage failures.",
                    age_hours=age,
                    identity_coverage=coverage,
                    usable_market_players=players,
                    required_source_failures=list(required_failures),
                )
            )
        else:
            checks.append(
                self._check(
                    "NFL_HUB_READY",
                    "READY",
                    f"NFL Hub is current with {coverage:.1%} market identity coverage.",
                    age_hours=age,
                    identity_coverage=coverage,
                    usable_market_players=players,
                )
            )
            if str(snapshot.get("status") or "").upper() == "DEGRADED":
                checks.append(
                    self._check(
                        "NFL_HUB_OPTIONAL_SOURCE_DEGRADED",
                        "PROVISIONAL",
                        "Required NFL Hub sources are healthy, but at least one optional source is degraded.",
                        "Review /v1/nfl/hub before the draft if the degraded source becomes decision-relevant.",
                    )
                )
        return checks

    def _special_teams_context(self, *, now: datetime) -> tuple[dict[str, object] | None, set[str]]:
        snapshot = _load_json(self.special_teams_path)
        supported = set(
            _special_teams_support(snapshot, now=now, max_age_hours=36.0)
            if snapshot
            else ()
        )
        return snapshot, supported

    def _market_check(self) -> DoctorCheck:
        status = self.draft_service.market_status()
        if not bool(status.get("available")):
            return self._check(
                "LIVE_ADP_UNAVAILABLE",
                "PROVISIONAL",
                "True live ADP is unavailable; the board will use neutral market timing.",
                "Configure PSE_FANTASYPROS_API_KEY and run: python scripts/refresh_live_adp.py --season 2026",
                reason=status.get("reason"),
            )
        if bool(status.get("expired")):
            return self._check(
                "LIVE_ADP_EXPIRED",
                "PROVISIONAL",
                "Live ADP is older than 24 hours and has zero timing authority.",
                "Refresh live ADP before relying on return-to-next-pick probabilities.",
                age_seconds=status.get("age_seconds"),
            )
        if bool(status.get("stale")):
            return self._check(
                "LIVE_ADP_STALE",
                "PROVISIONAL",
                "Live ADP is older than six hours, so timing confidence is being reduced.",
                "Refresh live ADP for full timing confidence.",
                age_seconds=status.get("age_seconds"),
                freshness_confidence=status.get("freshness_confidence"),
            )
        return self._check(
            "LIVE_ADP_CURRENT",
            "READY",
            "Live ADP snapshot is current and integrity-verified.",
            age_seconds=status.get("age_seconds"),
            rows=status.get("rows"),
        )

    def _league_report(
        self,
        league_id: str,
        *,
        projections: pd.DataFrame | None,
        supported_special_teams: set[str],
        now: datetime,
    ) -> LeagueDoctorReport:
        try:
            snapshot = self.draft_service.load_snapshot(league_id)
        except FileNotFoundError:
            check = self._check(
                "LEAGUE_SNAPSHOT_MISSING",
                "BLOCKED",
                f"League snapshot {league_id!r} is not installed.",
                "Import/sync the real league. Do not create placeholder ownership or draft history.",
            )
            return LeagueDoctorReport(
                league_id=str(league_id),
                league_name=str(league_id),
                platform="unknown",
                status="BLOCKED",
                can_use_core_draft_board=False,
                scoring_contract_id=None,
                checks=(check,),
                blocking_reasons=(check.code,),
                provisional_reasons=(),
            )

        checks: list[DoctorCheck] = []
        config = league_config_from_snapshot(snapshot)
        contract_id = config.scoring_contract_id

        if not snapshot.rosters:
            checks.append(
                self._check(
                    "LEAGUE_ROSTERS_MISSING",
                    "BLOCKED",
                    "The league snapshot contains no real rosters.",
                    "Re-import the league with roster data before entering the War Room.",
                )
            )
        else:
            checks.append(
                self._check(
                    "LEAGUE_ROSTERS_PRESENT",
                    "READY",
                    f"Snapshot contains {len(snapshot.rosters)} rosters.",
                    roster_count=len(snapshot.rosters),
                )
            )

        imported_age = _age_hours(snapshot.identity.imported_at, now=now)
        if imported_age is None or imported_age > 0.5:
            checks.append(
                self._check(
                    "LEAGUE_SNAPSHOT_NEEDS_REFRESH",
                    "PROVISIONAL",
                    "League snapshot is not recent enough to treat ownership/pick state as live.",
                    "Open the Draft Room and force-refresh the platform snapshot before the first pick.",
                    age_hours=imported_age,
                )
            )
        else:
            checks.append(
                self._check(
                    "LEAGUE_SNAPSHOT_CURRENT",
                    "READY",
                    f"League snapshot is {imported_age * 60.0:.0f} minutes old.",
                    age_hours=imported_age,
                )
            )

        if projections is None or "scoring_contract_id" not in projections.columns:
            checks.append(
                self._check(
                    "SCORING_CONTRACT_PROJECTIONS_UNAVAILABLE",
                    "BLOCKED",
                    "Verified projections cannot be matched to the league scoring contract.",
                )
            )
        else:
            contract_frame = projections.loc[
                projections["scoring_contract_id"].astype(str).eq(contract_id)
            ].copy()
            if contract_frame.empty:
                checks.append(
                    self._check(
                        "SCORING_CONTRACT_PROJECTIONS_MISSING",
                        "BLOCKED",
                        f"Champion has no player slate for scoring contract {contract_id}.",
                    )
                )
            else:
                core = assess_league_readiness(contract_frame, _core_config(config))
                full = assess_league_readiness(contract_frame, config)
                if not core.ready:
                    checks.append(
                        self._check(
                            "CORE_LEAGUE_READINESS_BLOCKED",
                            "BLOCKED",
                            "Required QB/RB/WR/TE scoring or valuation coverage is not release-ready.",
                            "Inspect league scoring support before using recommendations.",
                            blocking_flags=list(core.blocking_flags),
                            readiness_score=core.score,
                        )
                    )
                else:
                    checks.append(
                        self._check(
                            "CORE_LEAGUE_READINESS_READY",
                            "READY",
                            f"Core league scoring/valuation readiness is green ({core.score:.0f}).",
                            readiness_score=core.score,
                            scoring_contract_id=contract_id,
                        )
                    )

                market_only = _required_market_only_positions(full)
                unsupported = [pos for pos in market_only if pos not in supported_special_teams]
                if unsupported:
                    checks.append(
                        self._check(
                            "SPECIAL_TEAMS_MARKET_SUPPORT_MISSING",
                            "BLOCKED",
                            "League requires market-only special teams without a current supported snapshot: "
                            + ", ".join(unsupported),
                            "Run: python scripts/refresh_special_teams_market.py --season 2026",
                            positions=unsupported,
                        )
                    )
                elif market_only:
                    checks.append(
                        self._check(
                            "SPECIAL_TEAMS_MARKET_ONLY",
                            "PROVISIONAL",
                            "K/DST guidance is current but remains external-market-only, not model authority.",
                            positions=list(market_only),
                        )
                    )

        if config.median_scoring:
            checks.append(
                self._check(
                    "MEDIAN_SCORING_POLICY_UNVALIDATED",
                    "PROVISIONAL",
                    "Median-game strategy remains an explicit unvalidated policy overlay.",
                )
            )

        unsupported_scoring = tuple(snapshot.metadata.get("unsupported_scoring_keys") or ())
        if unsupported_scoring:
            checks.append(
                self._check(
                    "UNSUPPORTED_LIVE_SCORING_KEYS",
                    "PROVISIONAL",
                    "The platform exposes scoring rules outside the maintained component model.",
                    "Review the listed rules before treating close player decisions as exact.",
                    keys=list(unsupported_scoring),
                )
            )

        market = self.draft_service._market_status_for_league(league_id)
        if not bool(market.get("available")):
            checks.append(
                self._check(
                    "LEAGUE_ADP_TIMING_UNAVAILABLE",
                    "PROVISIONAL",
                    "No compatible current ADP view is available for this league; timing stays neutral.",
                    requested_scoring=market.get("requested_scoring"),
                    requested_scope=market.get("requested_scope"),
                    reason=market.get("reason"),
                )
            )
        else:
            if bool(market.get("stale")):
                checks.append(
                    self._check(
                        "LEAGUE_ADP_TIMING_STALE",
                        "PROVISIONAL",
                        "League ADP timing is available but freshness confidence is reduced.",
                        effective_market_confidence=market.get("effective_market_confidence"),
                    )
                )
            if str(market.get("format_authority") or "") == "superflex_proxy_for_multi_qb":
                checks.append(
                    self._check(
                        "LEAGUE_ADP_FORMAT_PROXY",
                        "PROVISIONAL",
                        "Multi-QB timing uses a superflex-style OP market proxy, not exact 2QB authority.",
                        format_confidence=market.get("format_confidence"),
                    )
                )
            if not bool(market.get("stale")) and str(market.get("format_authority") or "") != "superflex_proxy_for_multi_qb":
                checks.append(
                    self._check(
                        "LEAGUE_ADP_TIMING_READY",
                        "READY",
                        "Compatible live ADP timing is current for this league.",
                        coverage_rate=market.get("coverage_rate"),
                    )
                )

        league_status = _status(checks)
        return LeagueDoctorReport(
            league_id=snapshot.identity.league_id,
            league_name=snapshot.identity.name,
            platform=snapshot.identity.platform,
            status=league_status,
            can_use_core_draft_board=not any(check.status == "BLOCKED" for check in checks),
            scoring_contract_id=contract_id,
            checks=tuple(checks),
            blocking_reasons=_reason_codes(checks, "BLOCKED"),
            provisional_reasons=_reason_codes(checks, "PROVISIONAL"),
        )

    def report(self, league_id: str | None = None) -> DraftDayDoctorReport:
        now = datetime.now(UTC)
        global_checks, projections = self._projection_checks(now=now)
        global_checks.extend(self._hub_checks(now=now))
        global_checks.append(self._market_check())
        _special_snapshot, supported_special = self._special_teams_context(now=now)

        if league_id:
            requested_ids = [str(league_id)]
        else:
            requested_ids = [str(item.get("league_id")) for item in self.draft_service.list_leagues()]
            requested_ids = [item for item in requested_ids if item and item != "None"]
            if not requested_ids:
                global_checks.append(
                    self._check(
                        "NO_REAL_LEAGUES_INSTALLED",
                        "BLOCKED",
                        "No real league snapshots are available to the Draft War Room.",
                        "Import the actual leagues before draft day.",
                    )
                )

        leagues = tuple(
            self._league_report(
                requested,
                projections=projections,
                supported_special_teams=supported_special,
                now=now,
            )
            for requested in dict.fromkeys(requested_ids)
        )

        combined_checks = list(global_checks)
        for league in leagues:
            combined_checks.extend(league.checks)
        status = _status(combined_checks)
        global_blocked = any(check.status == "BLOCKED" for check in global_checks)
        usable_leagues = [league for league in leagues if league.can_use_core_draft_board]
        return DraftDayDoctorReport(
            status=status,
            can_open_war_room=not global_blocked and bool(usable_leagues),
            all_requested_leagues_usable=(
                bool(leagues) and not global_blocked and all(league.can_use_core_draft_board for league in leagues)
            ),
            checks=tuple(global_checks),
            leagues=leagues,
            blocking_reasons=_reason_codes(combined_checks, "BLOCKED"),
            provisional_reasons=_reason_codes(combined_checks, "PROVISIONAL"),
            checked_at_utc=now.isoformat(),
        )
