from __future__ import annotations

from dataclasses import asdict, dataclass

from player_state_engine.fantasy.readiness import LeagueReadinessReport


@dataclass(frozen=True, slots=True)
class DraftQualificationReport:
    """One authoritative answer to whether the live draft surface is safe to act on."""

    status: str
    can_act: bool
    blocking_reasons: tuple[str, ...]
    caution_reasons: tuple[str, ...]
    league_inputs_ready: bool
    projection_fresh: bool
    live_snapshot_fresh: bool
    refresh_healthy: bool
    readiness_score: float
    projection_age_hours: float | None
    max_projection_age_hours: float
    snapshot_age_seconds: float
    stale_after_seconds: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def qualify_live_draft(
    readiness: LeagueReadinessReport,
    *,
    projection_age_hours: float | None,
    max_projection_age_hours: float,
    snapshot_age_seconds: float,
    stale_after_seconds: float,
    refresh_warning: str | None = None,
) -> DraftQualificationReport:
    """Combine static league readiness with live freshness into one fail-closed verdict.

    `LeagueReadinessReport` intentionally describes the projection pool and exact league
    contract only. Live-draft qualification adds operational facts that can change from
    second to second: projection artifact age, league-snapshot age and refresh health.

    A stale projection artifact or stale live room snapshot blocks action. Softer data
    limitations already represented as non-blocking readiness flags remain cautions.
    """

    if max_projection_age_hours <= 0:
        raise ValueError("max_projection_age_hours must be positive")
    if snapshot_age_seconds < 0:
        raise ValueError("snapshot_age_seconds must be non-negative")
    if stale_after_seconds <= 0:
        raise ValueError("stale_after_seconds must be positive")

    blockers = list(readiness.blocking_flags)
    cautions = [flag for flag in readiness.flags if flag not in blockers]

    projection_fresh = (
        projection_age_hours is not None
        and projection_age_hours >= 0
        and projection_age_hours <= max_projection_age_hours
    )
    if projection_age_hours is None:
        blockers.append("PROJECTION_ARTIFACT_UNAVAILABLE")
    elif projection_age_hours < 0:
        blockers.append("INVALID_PROJECTION_AGE")
    elif not projection_fresh:
        blockers.append("STALE_PROJECTIONS")

    live_snapshot_fresh = snapshot_age_seconds <= stale_after_seconds
    if not live_snapshot_fresh:
        blockers.append("STALE_LIVE_SNAPSHOT")

    refresh_healthy = not bool(refresh_warning)
    if refresh_warning:
        cautions.append("LIVE_REFRESH_WARNING")

    blockers = list(dict.fromkeys(blockers))
    cautions = [
        reason for reason in dict.fromkeys(cautions)
        if reason not in blockers
    ]

    if blockers:
        status = "BLOCKED"
    elif cautions:
        status = "CAUTION"
    else:
        status = "READY"

    return DraftQualificationReport(
        status=status,
        can_act=not blockers,
        blocking_reasons=tuple(blockers),
        caution_reasons=tuple(cautions),
        league_inputs_ready=readiness.ready,
        projection_fresh=projection_fresh,
        live_snapshot_fresh=live_snapshot_fresh,
        refresh_healthy=refresh_healthy,
        readiness_score=readiness.score,
        projection_age_hours=projection_age_hours,
        max_projection_age_hours=float(max_projection_age_hours),
        snapshot_age_seconds=float(snapshot_age_seconds),
        stale_after_seconds=float(stale_after_seconds),
    )
