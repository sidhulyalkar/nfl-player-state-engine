from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

ShowcasePhase = Literal["capture", "settle"]


@dataclass(frozen=True)
class ShadowShowcaseModel:
    frame: pd.DataFrame
    snapshot_id: str
    captured_at_utc: str
    prediction_cutoff_utc: str
    source: str


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _shadow_digest(payload: dict[str, object]) -> str:
    clean = dict(payload)
    clean.pop("content_sha256", None)
    return hashlib.sha256(_canonical_json(clean).encode("utf-8")).hexdigest()


def load_verified_shadow_showcase_model(
    path: str | Path,
    *,
    season: int,
    week: int,
) -> ShadowShowcaseModel:
    """Load one immutable shadow checkpoint as the model side of a showcase comparison.

    The shadow ledger is already the repository's no-hindsight weekly forecast authority. This
    adapter verifies its content digest before exposing only the production forecast fields needed
    by the read-only model-performance evaluator.
    """

    location = Path(path)
    payload = json.loads(location.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Shadow showcase source must be a JSON object.")

    expected = str(payload.get("content_sha256") or "")
    if not expected:
        raise ValueError("Shadow showcase source is missing content_sha256.")
    actual = _shadow_digest(payload)
    if actual != expected:
        raise ValueError(
            "Shadow showcase source failed content integrity verification: "
            f"expected {expected}, got {actual}."
        )

    if int(payload.get("season") or -1) != int(season):
        raise ValueError(
            f"Shadow season mismatch: expected {season}, got {payload.get('season')}."
        )
    if int(payload.get("week") or -1) != int(week):
        raise ValueError(f"Shadow week mismatch: expected {week}, got {payload.get('week')}.")

    forecasts = payload.get("forecasts")
    if not isinstance(forecasts, list) or not forecasts:
        raise ValueError("Shadow showcase source contains no forecasts.")
    frame = pd.DataFrame(forecasts)
    required = {
        "player_id",
        "production_q10",
        "production_q50",
        "production_q90",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Shadow showcase forecasts are missing columns: {missing}")
    if frame["player_id"].astype(str).duplicated().any():
        raise ValueError("Shadow showcase forecasts contain duplicate player_id rows.")

    q10 = pd.to_numeric(frame["production_q10"], errors="coerce")
    q50 = pd.to_numeric(frame["production_q50"], errors="coerce")
    q90 = pd.to_numeric(frame["production_q90"], errors="coerce")
    invalid = q10.isna() | q50.isna() | q90.isna() | (q10 > q50) | (q50 > q90)
    if bool(invalid.any()):
        players = frame.loc[invalid, "player_id"].astype(str).head(8).tolist()
        raise ValueError(f"Shadow showcase forecasts contain invalid quantiles: {players}")

    captured = pd.Timestamp(payload.get("captured_at"))
    cutoff = pd.Timestamp(payload.get("prediction_cutoff"))
    if pd.isna(captured) or pd.isna(cutoff):
        raise ValueError("Shadow showcase source is missing capture/cutoff provenance.")
    if captured.tzinfo is None or cutoff.tzinfo is None:
        raise ValueError("Shadow showcase capture and cutoff timestamps must be timezone-aware.")
    captured = captured.tz_convert("UTC")
    cutoff = cutoff.tz_convert("UTC")
    if captured < cutoff:
        raise ValueError("Shadow showcase capture timestamp precedes its prediction cutoff.")

    checkpoint = str(payload.get("checkpoint") or "UNKNOWN").strip().upper()
    snapshot_id = str(payload.get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise ValueError("Shadow showcase source is missing snapshot_id.")

    return ShadowShowcaseModel(
        frame=frame,
        snapshot_id=snapshot_id,
        captured_at_utc=captured.isoformat(),
        prediction_cutoff_utc=cutoff.isoformat(),
        source=f"shadow_season:{checkpoint.lower()}",
    )


def resolve_regular_season_week(
    schedule: pd.DataFrame,
    *,
    season: int,
    phase: ShowcasePhase,
    as_of: date | datetime | pd.Timestamp,
) -> int:
    """Resolve the NFL week for a Wednesday capture or Tuesday settlement ritual.

    Resolution deliberately uses game dates rather than inferred kickoff timestamps. Capture picks
    the nearest regular-season week whose first game has not happened yet. Settlement picks the
    latest regular-season week whose final game date is already in the past.
    """

    required = {"season", "week", "gameday"}
    missing = sorted(required - set(schedule.columns))
    if missing:
        raise ValueError(f"Schedule is missing columns: {missing}")

    data = schedule.copy()
    data["season"] = pd.to_numeric(data["season"], errors="coerce")
    data["week"] = pd.to_numeric(data["week"], errors="coerce")
    if "game_type" in data:
        data = data.loc[data["game_type"].astype(str).str.upper().eq("REG")]
    data = data.loc[data["season"].eq(int(season))].copy()
    if data.empty:
        raise ValueError(f"No regular-season schedule rows found for {season}.")

    data["gameday"] = pd.to_datetime(data["gameday"], errors="coerce").dt.date
    data = data.loc[data["gameday"].notna() & data["week"].notna()].copy()
    if data.empty:
        raise ValueError(f"No dated regular-season schedule rows found for {season}.")

    grouped = (
        data.groupby("week", as_index=False)
        .agg(first_game=("gameday", "min"), last_game=("gameday", "max"))
        .sort_values("week")
    )
    grouped["week"] = grouped["week"].astype(int)
    resolved_date = pd.Timestamp(as_of).date()

    if phase == "capture":
        eligible = grouped.loc[grouped["first_game"] >= resolved_date]
        if eligible.empty:
            raise ValueError(f"No future regular-season week remains for {season}.")
        row = eligible.sort_values(["first_game", "week"]).iloc[0]
        return int(row["week"])

    if phase == "settle":
        eligible = grouped.loc[grouped["last_game"] < resolved_date]
        if eligible.empty:
            raise ValueError(f"No completed regular-season week is available for {season}.")
        row = eligible.sort_values(["last_game", "week"], ascending=False).iloc[0]
        return int(row["week"])

    raise ValueError("phase must be 'capture' or 'settle'.")
