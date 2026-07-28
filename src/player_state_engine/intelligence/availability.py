from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

PracticeStatus = Literal["full", "limited", "did_not_participate", "not_listed", "unknown"]
GameStatus = Literal[
    "active", "questionable", "doubtful", "out", "ir", "pup", "suspended", "unknown"
]

PRACTICE_SCORE = {
    "full": 1.0,
    "limited": 0.65,
    "did_not_participate": 0.2,
    "not_listed": 1.0,
    "unknown": 0.75,
}
GAME_SCORE = {
    "active": 1.0,
    "questionable": 0.72,
    "doubtful": 0.2,
    "out": 0.0,
    "ir": 0.0,
    "pup": 0.0,
    "suspended": 0.0,
    "unknown": 0.8,
}


class AvailabilityEvidence(BaseModel):
    player_id: str
    observed_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_url: str
    source_type: Literal[
        "official_injury_report", "team_transaction", "press_conference", "licensed_news", "manual"
    ]
    practice_status: PracticeStatus = "unknown"
    game_status: GameStatus = "unknown"
    body_area: str | None = None
    evidence_text: str | None = None
    source_reliability: float = Field(default=0.8, ge=0.0, le=1.0)


def build_availability_features(evidence: pd.DataFrame) -> pd.DataFrame:
    """Convert timestamped availability evidence into point-in-time model features.

    Each output row is a snapshot at an evidence timestamp. The downstream as-of
    join selects only snapshots known before kickoff.
    """

    required = {"player_id", "observed_at_utc", "practice_status", "game_status"}
    missing = required - set(evidence.columns)
    if missing:
        raise ValueError(f"Availability evidence missing columns: {sorted(missing)}")
    data = evidence.copy()
    data["observed_at_utc"] = pd.to_datetime(data["observed_at_utc"], utc=True, errors="raise")
    data["source_reliability"] = (
        pd.to_numeric(data.get("source_reliability", 0.8), errors="coerce").fillna(0.8).clip(0, 1)
    )
    data["availability_practice_score"] = (
        data["practice_status"].map(PRACTICE_SCORE).fillna(PRACTICE_SCORE["unknown"])
    )
    data["availability_game_score"] = (
        data["game_status"].map(GAME_SCORE).fillna(GAME_SCORE["unknown"])
    )
    data["availability_expected_active"] = (
        0.35 * data["availability_practice_score"] + 0.65 * data["availability_game_score"]
    ) * data["source_reliability"]
    data["availability_is_out"] = (
        data["game_status"].isin({"out", "ir", "pup", "suspended"}).astype(int)
    )
    data["availability_is_questionable"] = data["game_status"].eq("questionable").astype(int)
    data["availability_is_limited"] = data["practice_status"].eq("limited").astype(int)
    data["as_of_utc"] = data["observed_at_utc"]
    keep = [
        "player_id",
        "as_of_utc",
        "availability_practice_score",
        "availability_game_score",
        "availability_expected_active",
        "availability_is_out",
        "availability_is_questionable",
        "availability_is_limited",
        "source_reliability",
    ]
    return data.sort_values(["player_id", "as_of_utc"])[keep].reset_index(drop=True)


OfficialEventType = Literal[
    "practice_participation",
    "game_designation",
    "inactive_list",
    "injured_reserve",
    "transaction",
    "depth_chart",
    "coach_workload",
]
DepthRole = Literal["starter", "committee", "backup", "practice_squad", "unknown"]


class OfficialAvailabilityEvidence(BaseModel):
    """Normalized first-party evidence affecting availability or workload."""

    evidence_id: str
    player_id: str
    observed_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_url: str
    event_type: OfficialEventType
    practice_status: PracticeStatus = "unknown"
    game_status: GameStatus = "unknown"
    is_inactive: bool | None = None
    transaction_status: Literal[
        "activated", "signed", "waived", "released", "ir", "pup", "suspended", "unknown"
    ] = "unknown"
    depth_role: DepthRole = "unknown"
    depth_rank: int | None = Field(default=None, ge=1, le=10)
    expected_workload_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_text: str | None = None
    source_reliability: float = Field(default=0.95, ge=0.0, le=1.0)


_DEPTH_SCORE = {
    "starter": 1.0,
    "committee": 0.65,
    "backup": 0.3,
    "practice_squad": 0.05,
    "unknown": 0.6,
}


def build_official_availability_features(evidence: pd.DataFrame) -> pd.DataFrame:
    """Create cumulative point-in-time snapshots from official evidence families.

    The output retains a feature for each evidence family so experiments can
    activate practice, designation, inactive, transaction, depth-chart, and
    coach-workload information one family at a time.
    """

    required = {"player_id", "observed_at_utc", "event_type"}
    missing = required - set(evidence.columns)
    if missing:
        raise ValueError(f"Official availability evidence missing columns: {sorted(missing)}")
    data = evidence.copy()
    data["observed_at_utc"] = pd.to_datetime(data["observed_at_utc"], utc=True, errors="raise")
    defaults: dict[str, object] = {
        "practice_status": "unknown",
        "game_status": "unknown",
        "is_inactive": False,
        "transaction_status": "unknown",
        "depth_role": "unknown",
        "depth_rank": np.nan,
        "expected_workload_fraction": np.nan,
        "source_reliability": 0.95,
    }
    for column, default in defaults.items():
        if column not in data:
            data[column] = default
    data["source_reliability"] = (
        pd.to_numeric(data["source_reliability"], errors="coerce").fillna(0.95).clip(0, 1)
    )
    data = data.sort_values(["player_id", "observed_at_utc"]).reset_index(drop=True)

    rows: list[dict[str, object]] = []
    state: dict[str, dict[str, object]] = {}
    for record in data.to_dict("records"):
        player_id = str(record["player_id"])
        current = state.setdefault(
            player_id,
            {
                "availability_practice_score": 0.75,
                "availability_game_score": 0.8,
                "availability_inactive": 0.0,
                "availability_ir_or_pup": 0.0,
                "availability_transaction_active": 0.5,
                "availability_depth_score": 0.6,
                "availability_depth_rank": np.nan,
                "availability_coach_workload_fraction": np.nan,
                "availability_official_evidence_count": 0.0,
            },
        )
        reliability = float(record["source_reliability"])
        event_type = str(record["event_type"])
        if event_type == "practice_participation":
            current["availability_practice_score"] = (
                PRACTICE_SCORE.get(str(record["practice_status"]), 0.75) * reliability
            )
        elif event_type == "game_designation":
            current["availability_game_score"] = (
                GAME_SCORE.get(str(record["game_status"]), 0.8) * reliability
            )
        elif event_type == "inactive_list":
            current["availability_inactive"] = float(bool(record["is_inactive"]))
        elif event_type == "injured_reserve":
            status = str(record["transaction_status"])
            current["availability_ir_or_pup"] = float(
                status in {"ir", "pup"} or str(record["game_status"]) in {"ir", "pup"}
            )
        elif event_type == "transaction":
            status = str(record["transaction_status"])
            current["availability_transaction_active"] = {
                "activated": 1.0,
                "signed": 0.85,
                "waived": 0.0,
                "released": 0.0,
                "ir": 0.0,
                "pup": 0.0,
                "suspended": 0.0,
            }.get(status, 0.5)
        elif event_type == "depth_chart":
            current["availability_depth_score"] = _DEPTH_SCORE.get(str(record["depth_role"]), 0.6)
            current["availability_depth_rank"] = pd.to_numeric(
                record["depth_rank"], errors="coerce"
            )
        elif event_type == "coach_workload":
            current["availability_coach_workload_fraction"] = pd.to_numeric(
                record["expected_workload_fraction"], errors="coerce"
            )
        current["availability_official_evidence_count"] = (
            float(current["availability_official_evidence_count"]) + 1.0
        )

        active = (
            0.25 * float(current["availability_practice_score"])
            + 0.35 * float(current["availability_game_score"])
            + 0.15 * float(current["availability_transaction_active"])
            + 0.25 * float(current["availability_depth_score"])
        )
        if float(current["availability_inactive"]) or float(current["availability_ir_or_pup"]):
            active = 0.0
        workload = current["availability_coach_workload_fraction"]
        if pd.isna(workload):
            workload = float(current["availability_depth_score"]) * float(
                current["availability_practice_score"]
            )
        rows.append(
            {
                "player_id": player_id,
                "as_of_utc": record["observed_at_utc"],
                **current,
                "availability_expected_active": float(np.clip(active, 0.0, 1.0)),
                "availability_expected_workload_fraction": float(np.clip(workload, 0.0, 1.0)),
                "availability_latest_event_reliability": reliability,
            }
        )
    return pd.DataFrame(rows).sort_values(["player_id", "as_of_utc"]).reset_index(drop=True)
