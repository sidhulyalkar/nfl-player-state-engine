from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

StructuredEventType = Literal[
    "injury_out",
    "injury_questionable",
    "practice_dnp",
    "practice_limited",
    "practice_full",
    "depth_starter",
    "depth_backup",
    "snap_share",
]


class StructuredRoleEvent(BaseModel):
    player_id: str
    event_type: StructuredEventType
    latent_state: str
    direction: float = Field(ge=-1.0, le=1.0)
    magnitude: float = Field(ge=0.0, le=1.0)
    occurred_at_utc: datetime
    source: str
    evidence_class: str = "OFFICIAL"
    source_reliability: float = Field(default=0.95, ge=0.0, le=1.0)
    half_life_days: float = Field(default=7.0, gt=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _first(row: pd.Series, names: tuple[str, ...]) -> Any:
    for name in names:
        if name in row and pd.notna(row[name]):
            return row[name]
    return None


def _timestamp(value: object) -> datetime:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return datetime.now(UTC)
    return parsed.to_pydatetime()


def injuries_to_role_events(frame: pd.DataFrame) -> list[StructuredRoleEvent]:
    """Turn nflverse injury/practice rows into typed availability evidence."""
    events: list[StructuredRoleEvent] = []
    for _, row in frame.iterrows():
        player_id = _first(row, ("gsis_id", "player_id", "nflverse_id"))
        if player_id is None:
            continue
        occurred = _timestamp(
            _first(row, ("report_date", "date", "game_date", "updated_at", "season"))
        )
        practice = str(
            _first(row, ("practice_status", "practice_status_description", "practice")) or ""
        ).lower()
        status = str(
            _first(row, ("report_status", "game_status", "status", "injury_status")) or ""
        ).lower()
        metadata = {
            key: row[key]
            for key in ("season", "week", "team", "full_name", "primary_injury")
            if key in row and pd.notna(row[key])
        }
        if "out" in status or "inactive" in status:
            events.append(
                StructuredRoleEvent(
                    player_id=str(player_id),
                    event_type="injury_out",
                    latent_state="availability",
                    direction=-1.0,
                    magnitude=1.0,
                    occurred_at_utc=occurred,
                    source="nflverse_injuries",
                    half_life_days=2.0,
                    metadata=metadata,
                )
            )
        elif "question" in status or "doubt" in status:
            events.append(
                StructuredRoleEvent(
                    player_id=str(player_id),
                    event_type="injury_questionable",
                    latent_state="availability",
                    direction=-0.45,
                    magnitude=0.8,
                    occurred_at_utc=occurred,
                    source="nflverse_injuries",
                    half_life_days=3.0,
                    metadata=metadata,
                )
            )
        if "did not" in practice or practice == "dnp":
            event_type, direction, magnitude = "practice_dnp", -0.65, 0.8
        elif "limited" in practice:
            event_type, direction, magnitude = "practice_limited", -0.30, 0.6
        elif "full" in practice:
            event_type, direction, magnitude = "practice_full", 0.25, 0.5
        else:
            continue
        events.append(
            StructuredRoleEvent(
                player_id=str(player_id),
                event_type=event_type,
                latent_state="availability",
                direction=direction,
                magnitude=magnitude,
                occurred_at_utc=occurred,
                source="nflverse_injuries",
                half_life_days=3.0,
                metadata=metadata,
            )
        )
    return events


def depth_charts_to_role_events(frame: pd.DataFrame) -> list[StructuredRoleEvent]:
    """Translate current depth-chart order into role-security evidence."""
    events: list[StructuredRoleEvent] = []
    for _, row in frame.iterrows():
        player_id = _first(row, ("gsis_id", "player_id", "nflverse_id"))
        if player_id is None:
            continue
        raw_rank = _first(row, ("depth_team", "depth_position", "depth_rank", "order"))
        try:
            rank = int(float(raw_rank))
        except (TypeError, ValueError):
            text = str(raw_rank or "").lower()
            rank = 1 if text in {"starter", "first", "1st"} else 2 if text in {"backup", "second", "2nd"} else 0
        if rank not in {1, 2}:
            continue
        occurred = _timestamp(_first(row, ("dt", "date", "updated_at", "season")))
        starter = rank == 1
        events.append(
            StructuredRoleEvent(
                player_id=str(player_id),
                event_type="depth_starter" if starter else "depth_backup",
                latent_state="starter_security",
                direction=0.75 if starter else -0.25,
                magnitude=0.75 if starter else 0.45,
                occurred_at_utc=occurred,
                source="nflverse_depth_charts",
                evidence_class="REPORTED",
                source_reliability=0.85,
                half_life_days=10.0,
                metadata={
                    key: row[key]
                    for key in ("club_code", "team", "position", "full_name", "formation")
                    if key in row and pd.notna(row[key])
                },
            )
        )
    return events


def snap_counts_to_role_events(frame: pd.DataFrame) -> list[StructuredRoleEvent]:
    """Use observed offensive snap share as direct role evidence, never as a news sentiment proxy."""
    events: list[StructuredRoleEvent] = []
    for _, row in frame.iterrows():
        player_id = _first(row, ("pfr_player_id", "gsis_id", "player_id", "nflverse_id"))
        if player_id is None:
            continue
        share = _first(
            row,
            (
                "offense_pct",
                "offense_percentage",
                "offense_snap_pct",
                "snap_share",
            ),
        )
        if share is None:
            snaps = _first(row, ("offense_snaps", "offense"))
            team_snaps = _first(row, ("team_offense_snaps", "team_snaps"))
            try:
                share = float(snaps) / float(team_snaps) if float(team_snaps) > 0 else None
            except (TypeError, ValueError):
                share = None
        try:
            numeric = float(str(share).replace("%", ""))
        except (TypeError, ValueError):
            continue
        if numeric > 1.0:
            numeric /= 100.0
        numeric = min(1.0, max(0.0, numeric))
        occurred = _timestamp(_first(row, ("game_date", "date", "week", "season")))
        events.append(
            StructuredRoleEvent(
                player_id=str(player_id),
                event_type="snap_share",
                latent_state="snap_share",
                direction=2.0 * numeric - 1.0,
                magnitude=max(0.2, abs(2.0 * numeric - 1.0)),
                occurred_at_utc=occurred,
                source="nflverse_snap_counts",
                evidence_class="DIRECT_OBSERVATION",
                source_reliability=0.98,
                half_life_days=14.0,
                metadata={"snap_share": numeric},
            )
        )
    return events


def aggregate_structured_role_events(
    events: list[StructuredRoleEvent],
    *,
    as_of_utc: datetime | None = None,
) -> pd.DataFrame:
    """Create player-level decayed latent states from structured official/observed evidence."""
    if not events:
        return pd.DataFrame()
    as_of = as_of_utc or max(event.occurred_at_utc for event in events)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    grouped: dict[str, list[StructuredRoleEvent]] = defaultdict(list)
    for event in events:
        if event.occurred_at_utc <= as_of:
            grouped[event.player_id].append(event)
    rows: list[dict[str, object]] = []
    for player_id, history in grouped.items():
        sums: dict[str, float] = defaultdict(float)
        weights: dict[str, float] = defaultdict(float)
        sources: set[str] = set()
        for event in history:
            age = max((as_of - event.occurred_at_utc).total_seconds() / 86400.0, 0.0)
            recency = math.exp(-math.log(2.0) * age / event.half_life_days)
            weight = recency * event.source_reliability * event.magnitude
            sums[event.latent_state] += event.direction * weight
            weights[event.latent_state] += weight
            sources.add(event.source)
        row: dict[str, object] = {
            "player_id": player_id,
            "as_of_utc": as_of,
            "structured_role_event_count": len(history),
            "structured_role_source_count": len(sources),
        }
        for state, total in sums.items():
            row[f"structured_state_{state}"] = total / max(weights[state], 1e-9)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("player_id").reset_index(drop=True)
