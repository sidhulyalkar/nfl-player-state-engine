from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd


@dataclass(slots=True, frozen=True)
class SourceAvailabilityRecord:
    """Publication-time provenance contract for live-safe historical replay."""

    source_family: str
    event_time: datetime | None
    published_at: datetime | None
    first_observed_at: datetime | None
    retrieved_at: datetime
    available_for_prediction_at: datetime
    coverage: float | None = None
    license: str | None = None
    source_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "event_time",
            "published_at",
            "first_observed_at",
            "retrieved_at",
            "available_for_prediction_at",
        ):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.coverage is not None and not 0.0 <= self.coverage <= 1.0:
            raise ValueError("coverage must be in [0, 1]")

    def is_available(self, prediction_cutoff: datetime) -> bool:
        if prediction_cutoff.tzinfo is None:
            raise ValueError("prediction_cutoff must be timezone-aware")
        return self.available_for_prediction_at <= prediction_cutoff

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def infer_available_at(
    *,
    published_at: datetime | None,
    first_observed_at: datetime | None,
    retrieved_at: datetime,
) -> datetime:
    """Return the earliest defensible time the engine could have known a record."""
    candidates = [value for value in (published_at, first_observed_at) if value is not None]
    if not candidates:
        return retrieved_at
    return max(candidates)


def filter_point_in_time(
    frame: pd.DataFrame,
    *,
    prediction_cutoff: datetime,
    available_column: str = "available_for_prediction_at",
) -> pd.DataFrame:
    if prediction_cutoff.tzinfo is None:
        raise ValueError("prediction_cutoff must be timezone-aware")
    if available_column not in frame:
        raise ValueError(f"Missing publication-time provenance column: {available_column}")
    available = pd.to_datetime(frame[available_column], errors="coerce", utc=True)
    cutoff = pd.Timestamp(prediction_cutoff).tz_convert("UTC")
    return frame.loc[available.notna() & available.le(cutoff)].copy()


def validate_no_future_evidence(
    records: Iterable[SourceAvailabilityRecord],
    *,
    prediction_cutoff: datetime,
) -> None:
    future = [record for record in records if not record.is_available(prediction_cutoff)]
    if future:
        families = sorted({record.source_family for record in future})
        raise ValueError(
            "Future evidence crossed the prediction cutoff for source families: "
            + ", ".join(families)
        )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
