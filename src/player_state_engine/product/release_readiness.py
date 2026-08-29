from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import LeagueReadinessReport, assess_league_readiness

ReleaseStatus = Literal["READY", "PROVISIONAL", "BLOCKED"]
EXPECTED_HUB_AUTHORITY = "observational_nfl_state_only"
EXPECTED_PROJECTION_AUTHORITY = "production_approved"
EXPECTED_SPECIAL_TEAMS_AUTHORITY = "external_market_only"
DEFAULT_MARKET_ONLY_POSITIONS = ("DST", "K")


@dataclass(frozen=True, slots=True)
class LeagueReleaseStatus:
    league: str
    status: ReleaseStatus
    readiness: LeagueReadinessReport
    blocking_reasons: tuple[str, ...]
    provisional_reasons: tuple[str, ...]
    market_only_positions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["readiness"] = self.readiness.as_dict()
        return payload


@dataclass(frozen=True, slots=True)
class Sept1ReleaseReport:
    status: ReleaseStatus
    package_version: str
    projection_authority: str
    projection_integrity_verified: bool
    projection_age_hours: float | None
    hub_status: str
    hub_age_hours: float | None
    special_teams_market_age_hours: float | None
    special_teams_supported_positions: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    provisional_reasons: tuple[str, ...]
    leagues: tuple[LeagueReleaseStatus, ...]

    @property
    def can_use_core_draft_board(self) -> bool:
        return self.status in {"READY", "PROVISIONAL"}

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "package_version": self.package_version,
            "projection_authority": self.projection_authority,
            "projection_integrity_verified": self.projection_integrity_verified,
            "projection_age_hours": self.projection_age_hours,
            "hub_status": self.hub_status,
            "hub_age_hours": self.hub_age_hours,
            "special_teams_market_age_hours": self.special_teams_market_age_hours,
            "special_teams_supported_positions": list(self.special_teams_supported_positions),
            "blocking_reasons": list(self.blocking_reasons),
            "provisional_reasons": list(self.provisional_reasons),
            "can_use_core_draft_board": self.can_use_core_draft_board,
            "leagues": [league.as_dict() for league in self.leagues],
            "authority_note": (
                "PROVISIONAL never upgrades model authority. It only means every remaining "
                "exception is explicitly isolated to a verified non-model lane such as fresh "
                "market-only K/DST guidance or an optional NFL Hub source outage."
            ),
        }


def _parse_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _age_hours(value: object, *, now: datetime) -> float | None:
    parsed = _parse_utc(value)
    if parsed is None:
        return None
    delta = now.astimezone(UTC) - parsed
    return max(0.0, float(delta.total_seconds() / 3600.0))


def _special_teams_support(
    snapshot: Mapping[str, Any] | None,
    *,
    now: datetime,
    max_age_hours: float,
    minimum_entries_per_position: int,
) -> tuple[set[str], float | None]:
    if not snapshot:
        return set(), None
    if str(snapshot.get("authority") or "") != EXPECTED_SPECIAL_TEAMS_AUTHORITY:
        return set(), _age_hours(snapshot.get("generated_at_utc"), now=now)
    if snapshot.get("model_fields_present") is not False:
        return set(), _age_hours(snapshot.get("generated_at_utc"), now=now)

    age = _age_hours(snapshot.get("generated_at_utc"), now=now)
    if age is None or age > max_age_hours:
        return set(), age

    supported: set[str] = set()
    for position, count_field in (("K", "kicker_count"), ("DST", "dst_count")):
        try:
            count = int(snapshot.get(count_field) or 0)
        except (TypeError, ValueError):
            count = 0
        if count >= minimum_entries_per_position:
            supported.add(position)
    return supported, age


def _league_release_status(
    name: str,
    report: LeagueReadinessReport,
    *,
    market_only_positions: set[str],
    supported_market_only_positions: set[str],
) -> LeagueReleaseStatus:
    if report.ready:
        return LeagueReleaseStatus(
            league=name,
            status="READY",
            readiness=report,
            blocking_reasons=(),
            provisional_reasons=(),
            market_only_positions=(),
        )

    affected_positions = set(report.missing_positions) | set(report.inexact_required_positions)
    allowed_flags = {
        "MISSING_REQUIRED_POSITIONS",
        "INEXACT_REQUIRED_POSITION_SCORING",
        "READINESS_SCORE_BELOW_THRESHOLD",
    }
    unexpected_blockers = set(report.blocking_flags) - allowed_flags
    isolated_market_only = bool(affected_positions) and affected_positions.issubset(
        market_only_positions
    )
    market_support_complete = affected_positions.issubset(supported_market_only_positions)
    if not unexpected_blockers and isolated_market_only and market_support_complete:
        positions = tuple(sorted(affected_positions))
        return LeagueReleaseStatus(
            league=name,
            status="PROVISIONAL",
            readiness=report,
            blocking_reasons=(),
            provisional_reasons=(
                "MARKET_ONLY_REQUIRED_POSITIONS:" + ",".join(positions),
            ),
            market_only_positions=positions,
        )

    reasons = [f"LEAGUE_{name}:{flag}" for flag in report.blocking_flags]
    unsupported = sorted(
        affected_positions & market_only_positions - supported_market_only_positions
    )
    if isolated_market_only and unsupported:
        reasons.append(f"LEAGUE_{name}:MARKET_ONLY_SUPPORT_MISSING:{','.join(unsupported)}")
    if not reasons:
        reasons = [f"LEAGUE_{name}:READINESS_NOT_QUALIFIED"]
    return LeagueReleaseStatus(
        league=name,
        status="BLOCKED",
        readiness=report,
        blocking_reasons=tuple(dict.fromkeys(reasons)),
        provisional_reasons=(),
        market_only_positions=(),
    )


def assess_sept1_release_readiness(
    projections: pd.DataFrame,
    leagues: Mapping[str, LeagueConfig],
    *,
    package_version: str,
    projection_authority: str,
    projection_integrity_verified: bool,
    projection_source_cutoff_utc: object,
    nfl_hub_snapshot: Mapping[str, Any],
    special_teams_market_snapshot: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    required_version_prefix: str = "0.17.",
    market_only_positions: Sequence[str] = DEFAULT_MARKET_ONLY_POSITIONS,
    max_projection_age_hours: float = 48.0,
    max_hub_age_hours: float = 12.0,
    max_special_teams_market_age_hours: float = 48.0,
    minimum_special_teams_entries_per_position: int = 8,
    minimum_hub_player_count: int = 500,
    minimum_redraft_market_identity_coverage: float = 0.80,
    minimum_usable_market_players: int = 100,
) -> Sept1ReleaseReport:
    """Produce one fail-closed release verdict for the Sept. 1 draft product.

    `READY` is intentionally difficult to earn. `PROVISIONAL` is narrower: it is available only
    when every unresolved league exception is isolated to explicitly declared, fresh market-only
    positions with real coverage and/or the NFL Hub has only optional-source degradation. Neither
    state can be reached without an immutable, production-approved projection bundle and fresh core
    inputs.
    """

    if max_projection_age_hours <= 0.0:
        raise ValueError("max_projection_age_hours must be positive")
    if max_hub_age_hours <= 0.0:
        raise ValueError("max_hub_age_hours must be positive")
    if max_special_teams_market_age_hours <= 0.0:
        raise ValueError("max_special_teams_market_age_hours must be positive")
    if minimum_special_teams_entries_per_position < 1:
        raise ValueError("minimum_special_teams_entries_per_position must be positive")
    if minimum_hub_player_count < 1:
        raise ValueError("minimum_hub_player_count must be positive")
    if minimum_usable_market_players < 1:
        raise ValueError("minimum_usable_market_players must be positive")
    if not 0.0 <= minimum_redraft_market_identity_coverage <= 1.0:
        raise ValueError("minimum_redraft_market_identity_coverage must be between zero and one")
    if not leagues:
        raise ValueError("At least one league contract is required")

    evaluated_at = now or datetime.now(UTC)
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=UTC)
    evaluated_at = evaluated_at.astimezone(UTC)

    blockers: list[str] = []
    provisional: list[str] = []

    if not package_version.startswith(required_version_prefix):
        blockers.append("RELEASE_VERSION_NOT_FROZEN")
    if projection_authority != EXPECTED_PROJECTION_AUTHORITY:
        blockers.append("PROJECTION_BUNDLE_NOT_PRODUCTION_APPROVED")
    if not projection_integrity_verified:
        blockers.append("PROJECTION_BUNDLE_INTEGRITY_UNVERIFIED")

    projection_age = _age_hours(projection_source_cutoff_utc, now=evaluated_at)
    if projection_age is None:
        blockers.append("PROJECTION_SOURCE_CUTOFF_MISSING")
    elif projection_age > max_projection_age_hours:
        blockers.append("PROJECTION_SOURCE_CUTOFF_STALE")

    hub_authority = str(nfl_hub_snapshot.get("authority") or "")
    hub_status = str(nfl_hub_snapshot.get("status") or "UNAVAILABLE").upper()
    hub_age = _age_hours(nfl_hub_snapshot.get("generated_at_utc"), now=evaluated_at)
    if hub_authority != EXPECTED_HUB_AUTHORITY:
        blockers.append("NFL_HUB_AUTHORITY_INVALID")
    if hub_status in {"UNAVAILABLE", "STALE"}:
        blockers.append("NFL_HUB_NOT_CURRENT")
    elif hub_status == "DEGRADED":
        provisional.append("NFL_HUB_OPTIONAL_SOURCE_DEGRADED")
    elif hub_status != "READY":
        blockers.append("NFL_HUB_STATUS_UNKNOWN")
    if hub_age is None:
        blockers.append("NFL_HUB_TIMESTAMP_MISSING")
    elif hub_age > max_hub_age_hours:
        blockers.append("NFL_HUB_STALE")

    try:
        hub_players = int(nfl_hub_snapshot.get("player_count") or 0)
    except (TypeError, ValueError):
        hub_players = 0
    if hub_players < minimum_hub_player_count:
        blockers.append("NFL_HUB_PLAYER_COVERAGE_LOW")

    required_source_failures = tuple(
        str(value) for value in (nfl_hub_snapshot.get("required_source_failures") or [])
    )
    if required_source_failures:
        blockers.append("NFL_HUB_REQUIRED_SOURCE_FAILURE")

    market_identity = nfl_hub_snapshot.get("market_identity") or {}
    try:
        redraft_identity_coverage = float(
            market_identity.get("redraft_identity_coverage") or 0.0
        )
    except (TypeError, ValueError):
        redraft_identity_coverage = 0.0
    try:
        usable_market_players = int(market_identity.get("usable_market_players") or 0)
    except (TypeError, ValueError):
        usable_market_players = 0
    if redraft_identity_coverage < minimum_redraft_market_identity_coverage:
        blockers.append("NFL_HUB_MARKET_IDENTITY_COVERAGE_LOW")
    if usable_market_players < minimum_usable_market_players:
        blockers.append("NFL_HUB_MARKET_PLAYER_COVERAGE_LOW")

    allowed_market_positions = {str(position).upper() for position in market_only_positions}
    supported_market_positions, special_teams_age = _special_teams_support(
        special_teams_market_snapshot,
        now=evaluated_at,
        max_age_hours=max_special_teams_market_age_hours,
        minimum_entries_per_position=minimum_special_teams_entries_per_position,
    )
    supported_market_positions &= allowed_market_positions

    league_results = tuple(
        _league_release_status(
            name,
            assess_league_readiness(projections, config),
            market_only_positions=allowed_market_positions,
            supported_market_only_positions=supported_market_positions,
        )
        for name, config in sorted(leagues.items())
    )
    for league in league_results:
        blockers.extend(league.blocking_reasons)
        provisional.extend(f"LEAGUE_{league.league}:{reason}" for reason in league.provisional_reasons)

    blockers = list(dict.fromkeys(blockers))
    provisional = list(dict.fromkeys(provisional))
    status: ReleaseStatus
    if blockers:
        status = "BLOCKED"
    elif provisional:
        status = "PROVISIONAL"
    else:
        status = "READY"

    return Sept1ReleaseReport(
        status=status,
        package_version=package_version,
        projection_authority=projection_authority,
        projection_integrity_verified=bool(projection_integrity_verified),
        projection_age_hours=projection_age,
        hub_status=hub_status,
        hub_age_hours=hub_age,
        special_teams_market_age_hours=special_teams_age,
        special_teams_supported_positions=tuple(sorted(supported_market_positions)),
        blocking_reasons=tuple(blockers),
        provisional_reasons=tuple(provisional),
        leagues=league_results,
    )
