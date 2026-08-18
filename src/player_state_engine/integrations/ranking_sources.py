from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

AccessMode = Literal[
    "api",
    "nflreadpy",
    "platform_archive",
    "licensed_export",
    "manual_export",
    "public_snapshot",
]
SourceKind = Literal["expert", "market", "sharp_market", "projection", "news"]


@dataclass(frozen=True, slots=True)
class RankingSourceSpec:
    key: str
    display_name: str
    source_kind: SourceKind
    access_mode: AccessMode
    automated: bool
    supports_custom_formats: bool
    point_in_time_required: bool = True
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


RANKING_SOURCES: tuple[RankingSourceSpec, ...] = (
    RankingSourceSpec(
        "fantasypros_ecr",
        "FantasyPros ECR",
        "expert",
        "api",
        True,
        True,
        notes="Use API credentials; preserve expert dispersion and capture timestamp.",
    ),
    RankingSourceSpec(
        "fantasypros_adp",
        "FantasyPros ADP",
        "market",
        "api",
        True,
        True,
        notes="Official API market snapshot; capture the source timestamp before every draft replay.",
    ),
    RankingSourceSpec(
        "nflverse_ff_rankings",
        "nflverse ffverse rankings",
        "expert",
        "nflreadpy",
        True,
        False,
        notes="Historical/current FantasyPros-derived ffverse snapshots when available.",
    ),
    RankingSourceSpec(
        "fantasy_life",
        "Fantasy Life",
        "expert",
        "licensed_export",
        False,
        True,
        notes="Ingest licensed or user-provided exports; do not depend on brittle page scraping.",
    ),
    RankingSourceSpec(
        "espn_rankings",
        "ESPN Fantasy",
        "expert",
        "manual_export",
        False,
        True,
        notes="Useful league/platform benchmark when a permitted export is available.",
    ),
    RankingSourceSpec(
        "rotowire",
        "RotoWire",
        "expert",
        "licensed_export",
        False,
        True,
    ),
    RankingSourceSpec(
        "pff",
        "PFF Fantasy",
        "expert",
        "licensed_export",
        False,
        True,
    ),
    RankingSourceSpec(
        "rotoworld",
        "Rotoworld / NBC Sports",
        "expert",
        "public_snapshot",
        False,
        False,
        notes="Archive only permitted public snapshots or user-provided exports.",
    ),
    RankingSourceSpec(
        "sleeper_adp",
        "Sleeper draft market",
        "market",
        "platform_archive",
        True,
        True,
        notes="Prefer real draft archives and platform-specific empirical pick distributions.",
    ),
    RankingSourceSpec(
        "espn_adp",
        "ESPN draft market",
        "market",
        "platform_archive",
        True,
        True,
    ),
    RankingSourceSpec(
        "yahoo_adp",
        "Yahoo draft market",
        "market",
        "manual_export",
        False,
        True,
    ),
    RankingSourceSpec(
        "nffc_adp",
        "NFFC high-stakes market",
        "sharp_market",
        "licensed_export",
        False,
        True,
    ),
    RankingSourceSpec(
        "ffpc_adp",
        "FFPC high-stakes market",
        "sharp_market",
        "licensed_export",
        False,
        True,
    ),
    RankingSourceSpec(
        "underdog_adp",
        "Underdog best-ball market",
        "sharp_market",
        "licensed_export",
        False,
        False,
        notes="Treat as a liquid market sensor, not direct managed-league value.",
    ),
)


def ranking_source_catalog() -> list[dict[str, object]]:
    return [source.to_dict() for source in RANKING_SOURCES]


def source_spec(key: str) -> RankingSourceSpec | None:
    normalized = str(key).strip().lower()
    return next((source for source in RANKING_SOURCES if source.key == normalized), None)
