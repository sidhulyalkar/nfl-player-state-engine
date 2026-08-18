from __future__ import annotations

from dataclasses import asdict, dataclass

from player_state_engine.game_intelligence.schema import EvidenceAvailability


@dataclass(slots=True, frozen=True)
class GameEvidenceSource:
    name: str
    category: str
    availability: EvidenceAvailability
    cadence: str
    point_in_time_safe: bool
    notes: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def game_evidence_catalog() -> list[dict[str, object]]:
    """Describe evidence lanes and their safe prediction-time roles."""
    sources = [
        GameEvidenceSource(
            "nflverse_pbp",
            "play_by_play",
            EvidenceAvailability.LIVE,
            "nightly plus game-day updates",
            True,
            "Primary state-transition, play-call, EPA, pace, score and opportunity evidence.",
        ),
        GameEvidenceSource(
            "nflverse_schedules",
            "game_environment",
            EvidenceAvailability.LIVE,
            "minutes",
            True,
            "Schedule, results and public game-environment fields available before kickoff.",
        ),
        GameEvidenceSource(
            "nflverse_depth_charts",
            "role_state",
            EvidenceAvailability.LIVE,
            "daily",
            True,
            "Timestamped from 2025 onward; use only records loaded before prediction cutoff.",
        ),
        GameEvidenceSource(
            "nflverse_snap_counts",
            "role_state",
            EvidenceAvailability.LIVE_FAIL_SOFT,
            "four times daily in season",
            True,
            "Historical/current snap evidence; upstream source availability can lag.",
        ),
        GameEvidenceSource(
            "nflverse_nextgen_stats",
            "player_efficiency",
            EvidenceAvailability.LIVE_FAIL_SOFT,
            "nightly in season",
            True,
            "Weekly NGS player efficiency and expected-performance aggregates.",
        ),
        GameEvidenceSource(
            "nflverse_ftn_charting",
            "play_structure",
            EvidenceAvailability.LIVE_FAIL_SOFT,
            "four times daily in season",
            True,
            "Motion, play action, RPO, screens, blitzers and other charted structure.",
        ),
        GameEvidenceSource(
            "nflverse_participation",
            "formation_personnel",
            EvidenceAvailability.RETROSPECTIVE,
            "after postseason for 2023+",
            False,
            "Useful for retrospective representation learning; not a live 2026 feature feed.",
        ),
        GameEvidenceSource(
            "official_injury_evidence",
            "availability",
            EvidenceAvailability.MANUAL_LICENSED,
            "as published",
            True,
            "Use existing timestamped official-evidence ingestion; nflverse injury feed is not current.",
        ),
        GameEvidenceSource(
            "coach_registry",
            "coaching",
            EvidenceAvailability.MANUAL_LICENSED,
            "when staff/play-caller changes",
            True,
            "Timestamped head coach, coordinator and play-caller identities; never infer private intent.",
        ),
        GameEvidenceSource(
            "market_game_lines",
            "game_environment",
            EvidenceAvailability.MANUAL_LICENSED,
            "snapshot",
            True,
            "Spread/total are external probabilistic sensors, not football truth.",
        ),
    ]
    return [source.to_dict() for source in sources]
