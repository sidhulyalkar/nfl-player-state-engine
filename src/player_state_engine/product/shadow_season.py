from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SHADOW_SCHEMA_VERSION = 1
SHADOW_CHECKPOINTS = (
    "WEDNESDAY",
    "FRIDAY",
    "SUNDAY_PREGAME",
    "FINAL_DECISION",
)
_HINDSIGHT_TOKENS = ("actual", "realized", "regret", "outcome", "settled")
_PRODUCTION_QUANTILE_ALIASES = {
    "production_q10": ("production_q10", "week_points_q10", "fantasy_points_ppr_q10", "q10"),
    "production_q50": ("production_q50", "week_points_q50", "fantasy_points_ppr_q50", "q50"),
    "production_q90": ("production_q90", "week_points_q90", "fantasy_points_ppr_q90", "q90"),
}


def _utc_timestamp(value: datetime | str | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("timestamp is missing")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp


def _utc_iso(value: datetime | str | pd.Timestamp) -> str:
    return _utc_timestamp(value).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _content_digest(payload: Mapping[str, object]) -> str:
    clean = dict(payload)
    clean.pop("content_sha256", None)
    return _sha256_text(_canonical_json(clean))


def _with_digest(payload: Mapping[str, object]) -> dict[str, object]:
    result = dict(payload)
    result["content_sha256"] = _content_digest(result)
    return result


def _verify_digest(payload: Mapping[str, object], *, label: str) -> None:
    expected = str(payload.get("content_sha256") or "")
    if not expected:
        raise ValueError(f"{label} is missing content_sha256")
    actual = _content_digest(payload)
    if actual != expected:
        raise ValueError(f"{label} integrity check failed: expected {expected}, got {actual}")


def _finite(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    try:
        if not bool(pd.notna(value)):
            return None
    except (TypeError, ValueError):
        return None
    text = str(value).strip()
    return text or None


def _coalesce_numeric_aliases(
    frame: pd.DataFrame,
    aliases: Sequence[str],
    *,
    target: str,
    tolerance: float = 1e-9,
) -> tuple[pd.Series, pd.Series]:
    values = pd.Series(np.nan, index=frame.index, dtype=float)
    sources = pd.Series(pd.NA, index=frame.index, dtype="string")
    for column in aliases:
        if column not in frame:
            continue
        candidate = pd.to_numeric(frame[column], errors="coerce")
        overlap = values.notna() & candidate.notna()
        if overlap.any():
            delta = (values.loc[overlap] - candidate.loc[overlap]).abs()
            if bool((delta > tolerance).any()):
                bad = list(delta.loc[delta > tolerance].index[:5])
                raise ValueError(
                    f"Conflicting aliases for {target}: column {column!r} disagrees on rows {bad}"
                )
        fill = values.isna() & candidate.notna()
        values.loc[fill] = candidate.loc[fill]
        sources.loc[fill] = column
    return values, sources


def _first_text_column(frame: pd.DataFrame, aliases: Sequence[str]) -> pd.Series:
    result = pd.Series(pd.NA, index=frame.index, dtype="object")
    for column in aliases:
        if column not in frame:
            continue
        candidate = frame[column]
        fill = result.isna() & candidate.notna()
        result.loc[fill] = candidate.loc[fill]
    return result


def normalize_production_forecasts(
    frame: pd.DataFrame,
    *,
    production_method: str = "direct_player_quantile_model",
) -> pd.DataFrame:
    """Normalize a live production projection artifact without importing hindsight fields."""

    if frame.empty:
        raise ValueError("Shadow snapshot requires a non-empty production projection frame")
    if "player_id" not in frame:
        raise ValueError("Shadow snapshot projection frame is missing player_id")

    out = pd.DataFrame(index=frame.index)
    out["player_id"] = frame["player_id"].astype(str)
    out["player_name"] = _first_text_column(frame, ("player_name", "name", "player"))
    out["position"] = _first_text_column(frame, ("position", "pos"))
    out["team"] = _first_text_column(frame, ("team", "recent_team", "nfl_team"))
    out["opponent"] = _first_text_column(frame, ("opponent", "opp"))

    for target, aliases in _PRODUCTION_QUANTILE_ALIASES.items():
        values, sources = _coalesce_numeric_aliases(frame, aliases, target=target)
        if values.isna().any():
            raise ValueError(f"Shadow snapshot is missing finite {target} values")
        out[target] = values.astype(float)
        out[f"{target}_source"] = sources

    crossed = (out["production_q10"] > out["production_q50"]) | (
        out["production_q50"] > out["production_q90"]
    )
    if crossed.any():
        players = out.loc[crossed, "player_id"].head(10).tolist()
        raise ValueError(f"Production quantiles cross for players: {players}")
    if out["player_id"].duplicated().any():
        duplicates = out.loc[out["player_id"].duplicated(keep=False), "player_id"].unique().tolist()
        raise ValueError(f"Shadow snapshot contains duplicate player_id rows: {duplicates[:10]}")

    optional_numeric = {
        "availability_probability": ("availability_probability", "probability_active"),
        "reliability_score": ("draft_reliability_score", "reliability_score"),
        "decision_score": ("live_draft_score", "decision_score", "draft_score"),
        "decision_rank": ("live_rank", "decision_rank", "rank"),
    }
    for target, aliases in optional_numeric.items():
        values, _ = _coalesce_numeric_aliases(frame, aliases, target=target)
        out[target] = values
    out["decision_action"] = _first_text_column(
        frame, ("guarded_draft_action", "draft_action", "decision_action")
    )
    out["production_method"] = str(production_method)
    return out.reset_index(drop=True)


def attach_research_challenger(
    production: pd.DataFrame,
    challenger: pd.DataFrame,
    *,
    challenger_method: str = "player_state_graph",
) -> pd.DataFrame:
    """Attach research-only challenger quantiles without changing production fields."""

    if production.empty:
        raise ValueError("Production shadow frame is empty")
    result = production.copy()
    for column in (
        "challenger_q10",
        "challenger_q50",
        "challenger_q90",
        "challenger_probability_active",
        "challenger_role_change_probability",
    ):
        result[column] = np.nan
    result["challenger_method"] = None
    result["challenger_authority"] = "research_only"
    result["challenger_may_change_decision"] = False

    if challenger.empty:
        return result
    if "player_id" not in challenger:
        raise ValueError("Challenger frame is missing player_id")
    graph = challenger.copy()
    graph["player_id"] = graph["player_id"].astype(str)
    if graph["player_id"].duplicated().any():
        raise ValueError("Challenger frame must contain at most one row per player_id")

    for target, aliases in {
        "challenger_q10": ("challenger_q10", "q10"),
        "challenger_q50": ("challenger_q50", "q50"),
        "challenger_q90": ("challenger_q90", "q90"),
        "challenger_probability_active": (
            "challenger_probability_active",
            "probability_active",
        ),
        "challenger_role_change_probability": (
            "challenger_role_change_probability",
            "role_change_probability",
        ),
    }.items():
        values, _ = _coalesce_numeric_aliases(graph, aliases, target=target)
        graph[target] = values

    selected = graph[
        [
            "player_id",
            "challenger_q10",
            "challenger_q50",
            "challenger_q90",
            "challenger_probability_active",
            "challenger_role_change_probability",
        ]
    ].copy()
    merged = result.drop(
        columns=[
            "challenger_q10",
            "challenger_q50",
            "challenger_q90",
            "challenger_probability_active",
            "challenger_role_change_probability",
        ]
    ).merge(selected, on="player_id", how="left", validate="one_to_one")
    has_challenger = merged[["challenger_q10", "challenger_q50", "challenger_q90"]].notna().all(axis=1)
    crossed = has_challenger & (
        (merged["challenger_q10"] > merged["challenger_q50"])
        | (merged["challenger_q50"] > merged["challenger_q90"])
    )
    if crossed.any():
        players = merged.loc[crossed, "player_id"].head(10).tolist()
        raise ValueError(f"Challenger quantiles cross for players: {players}")
    merged["challenger_method"] = np.where(has_challenger, challenger_method, None)
    merged["challenger_authority"] = "research_only"
    merged["challenger_may_change_decision"] = False
    return merged


def _assert_no_hindsight(value: object, *, path: str = "decision") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(token in key_text for token in _HINDSIGHT_TOKENS):
                raise ValueError(f"Shadow snapshot decision context contains hindsight field {path}.{key}")
            _assert_no_hindsight(child, path=f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _assert_no_hindsight(child, path=f"{path}[{index}]")


def _normalize_sources(
    sources: Sequence[Mapping[str, object]] | None,
    *,
    prediction_cutoff: pd.Timestamp,
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for raw in sources or ():
        name = str(raw.get("name") or "").strip()
        if not name:
            raise ValueError("Shadow source record is missing name")
        available_at_raw = raw.get("available_at")
        available_at = _utc_timestamp(available_at_raw) if available_at_raw is not None else None
        if available_at is not None and available_at > prediction_cutoff:
            raise ValueError(
                f"Source {name!r} became available after prediction cutoff: "
                f"{available_at.isoformat()} > {prediction_cutoff.isoformat()}"
            )
        normalized.append(
            {
                "name": name,
                "available_at": available_at.isoformat() if available_at is not None else None,
                "age_hours_at_cutoff": (
                    float((prediction_cutoff - available_at).total_seconds() / 3600.0)
                    if available_at is not None
                    else None
                ),
                "sha256": _optional_text(raw.get("sha256")),
                "path": _optional_text(raw.get("path")),
                "source_url": _optional_text(raw.get("source_url")),
            }
        )
    return sorted(normalized, key=lambda row: str(row["name"]))


def _snapshot_identity(
    *,
    season: int,
    week: int,
    checkpoint: str,
    league_key: str | None,
    prediction_cutoff: str,
) -> dict[str, object]:
    return {
        "season": int(season),
        "week": int(week),
        "checkpoint": checkpoint,
        "league_key": league_key,
        "prediction_cutoff": prediction_cutoff,
    }


def build_shadow_snapshot(
    forecasts: pd.DataFrame,
    *,
    season: int,
    week: int,
    checkpoint: str,
    prediction_cutoff: datetime | str | pd.Timestamp,
    captured_at: datetime | str | pd.Timestamp | None = None,
    league_key: str | None = None,
    sources: Sequence[Mapping[str, object]] | None = None,
    decision_records: Sequence[Mapping[str, object]] | None = None,
    model_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build one immutable, no-hindsight live shadow checkpoint."""

    checkpoint_name = str(checkpoint).strip().upper()
    if checkpoint_name not in SHADOW_CHECKPOINTS:
        raise ValueError(f"checkpoint must be one of {SHADOW_CHECKPOINTS}")
    if int(week) < 1 or int(week) > 18:
        raise ValueError("shadow-season week must be between 1 and 18")
    if int(season) < 2020:
        raise ValueError("shadow-season season is invalid")
    if forecasts.empty:
        raise ValueError("Shadow snapshot forecasts are empty")
    required = {"player_id", "production_q10", "production_q50", "production_q90"}
    missing = required - set(forecasts.columns)
    if missing:
        raise ValueError(f"Shadow snapshot forecasts missing columns: {sorted(missing)}")
    if forecasts["player_id"].astype(str).duplicated().any():
        raise ValueError("Shadow snapshot forecasts must contain one row per player_id")

    cutoff = _utc_timestamp(prediction_cutoff)
    captured = _utc_timestamp(captured_at or datetime.now(UTC))
    if captured < cutoff:
        raise ValueError("captured_at cannot precede prediction_cutoff")

    decisions = [dict(record) for record in (decision_records or ())]
    _assert_no_hindsight(decisions)
    normalized_sources = _normalize_sources(sources, prediction_cutoff=cutoff)

    safe_columns = [
        column
        for column in (
            "player_id",
            "player_name",
            "position",
            "team",
            "opponent",
            "production_q10",
            "production_q50",
            "production_q90",
            "production_q10_source",
            "production_q50_source",
            "production_q90_source",
            "production_method",
            "availability_probability",
            "reliability_score",
            "decision_score",
            "decision_rank",
            "decision_action",
            "challenger_q10",
            "challenger_q50",
            "challenger_q90",
            "challenger_probability_active",
            "challenger_role_change_probability",
            "challenger_method",
            "challenger_authority",
            "challenger_may_change_decision",
        )
        if column in forecasts
    ]
    safe = forecasts.loc[:, safe_columns].copy()
    for column in (
        "production_q10",
        "production_q50",
        "production_q90",
        "availability_probability",
        "reliability_score",
        "decision_score",
        "decision_rank",
        "challenger_q10",
        "challenger_q50",
        "challenger_q90",
        "challenger_probability_active",
        "challenger_role_change_probability",
    ):
        if column in safe:
            safe[column] = pd.to_numeric(safe[column], errors="coerce")
    production_crossed = (safe["production_q10"] > safe["production_q50"]) | (
        safe["production_q50"] > safe["production_q90"]
    )
    if production_crossed.any() or safe[["production_q10", "production_q50", "production_q90"]].isna().any(axis=None):
        raise ValueError("Shadow snapshot production quantiles must be finite and non-crossing")

    records = json.loads(safe.to_json(orient="records", date_format="iso"))
    identity = _snapshot_identity(
        season=int(season),
        week=int(week),
        checkpoint=checkpoint_name,
        league_key=str(league_key) if league_key is not None else None,
        prediction_cutoff=cutoff.isoformat(),
    )
    snapshot_id = _sha256_text(_canonical_json(identity))[:24]
    payload = {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "record_type": "shadow_checkpoint",
        "snapshot_id": snapshot_id,
        **identity,
        "captured_at": captured.isoformat(),
        "data_mode": "LIVE_SHADOW",
        "authority": {
            "production": "direct_player_quantile_model",
            "challenger": "research_only",
            "promotion_is_automatic": False,
            "snapshot_may_change_authority": False,
        },
        "sources": normalized_sources,
        "model_metadata": dict(model_metadata or {}),
        "decisions": decisions,
        "forecast_count": len(records),
        "forecasts": records,
    }
    return _with_digest(payload)


def _pinball(actual: float, prediction: float, quantile: float) -> float:
    error = actual - prediction
    return float(quantile * error if error >= 0 else (quantile - 1.0) * error)


def _metrics_from_rows(rows: Sequence[Mapping[str, object]], *, prefix: str) -> dict[str, object]:
    q10_name = f"{prefix}_q10"
    q50_name = f"{prefix}_q50"
    q90_name = f"{prefix}_q90"
    usable: list[tuple[float, float, float, float]] = []
    for row in rows:
        actual = _finite(row.get("actual"))
        q10 = _finite(row.get(q10_name))
        q50 = _finite(row.get(q50_name))
        q90 = _finite(row.get(q90_name))
        if None not in (actual, q10, q50, q90):
            usable.append((float(actual), float(q10), float(q50), float(q90)))
    if not usable:
        return {"n": 0}
    array = np.asarray(usable, dtype=float)
    actual = array[:, 0]
    q10 = array[:, 1]
    q50 = array[:, 2]
    q90 = array[:, 3]
    pinball_q10 = np.asarray([_pinball(a, p, 0.10) for a, p in zip(actual, q10, strict=True)])
    pinball_q50 = np.asarray([_pinball(a, p, 0.50) for a, p in zip(actual, q50, strict=True)])
    pinball_q90 = np.asarray([_pinball(a, p, 0.90) for a, p in zip(actual, q90, strict=True)])
    return {
        "n": int(len(array)),
        "q50_mae": float(np.mean(np.abs(actual - q50))),
        "mean_pinball": float(np.mean(np.column_stack([pinball_q10, pinball_q50, pinball_q90]))),
        "q10_pinball": float(pinball_q10.mean()),
        "q50_pinball": float(pinball_q50.mean()),
        "q90_pinball": float(pinball_q90.mean()),
        "interval_80_coverage": float(np.mean((actual >= q10) & (actual <= q90))),
        "mean_interval_width": float(np.mean(q90 - q10)),
        "calibration_cdf_q10": float(np.mean(actual <= q10)),
        "calibration_cdf_q50": float(np.mean(actual <= q50)),
        "calibration_cdf_q90": float(np.mean(actual <= q90)),
    }


def build_shadow_settlement(
    snapshot: Mapping[str, object],
    actuals: pd.DataFrame,
    *,
    settled_at: datetime | str | pd.Timestamp | None = None,
    actual_column: str = "actual",
    source_metadata: Mapping[str, object] | None = None,
    require_complete: bool = True,
) -> dict[str, object]:
    """Create an append-only settlement companion without mutating the original checkpoint."""

    _verify_digest(snapshot, label="shadow snapshot")
    if actuals.empty:
        raise ValueError("Shadow settlement actuals are empty")
    if "player_id" not in actuals or actual_column not in actuals:
        raise ValueError(f"Shadow settlement requires player_id and {actual_column}")
    actual_frame = actuals[["player_id", actual_column] + [
        column for column in ("active", "games_played", "source") if column in actuals
    ]].copy()
    actual_frame["player_id"] = actual_frame["player_id"].astype(str)
    actual_frame[actual_column] = pd.to_numeric(actual_frame[actual_column], errors="coerce")
    if actual_frame["player_id"].duplicated().any():
        raise ValueError("Shadow settlement actuals contain duplicate player_id rows")
    if actual_frame[actual_column].isna().any():
        raise ValueError("Shadow settlement actuals contain non-finite values")
    actual_by_player = actual_frame.set_index("player_id").to_dict(orient="index")

    forecast_rows = list(snapshot.get("forecasts") or [])
    missing_players: list[str] = []
    settled_rows: list[dict[str, object]] = []
    for forecast in forecast_rows:
        player_id = str(forecast.get("player_id"))
        actual_row = actual_by_player.get(player_id)
        if actual_row is None:
            missing_players.append(player_id)
            continue
        actual_value = float(actual_row[actual_column])
        row = {
            "player_id": player_id,
            "player_name": forecast.get("player_name"),
            "position": forecast.get("position"),
            "team": forecast.get("team"),
            "actual": actual_value,
            "production_q10": forecast.get("production_q10"),
            "production_q50": forecast.get("production_q50"),
            "production_q90": forecast.get("production_q90"),
            "challenger_q10": forecast.get("challenger_q10"),
            "challenger_q50": forecast.get("challenger_q50"),
            "challenger_q90": forecast.get("challenger_q90"),
            "active": actual_row.get("active"),
            "games_played": actual_row.get("games_played"),
        }
        settled_rows.append(row)
    if require_complete and missing_players:
        raise ValueError(
            f"Shadow settlement is missing actuals for {len(missing_players)} forecast players: "
            f"{missing_players[:10]}"
        )

    production_metrics = _metrics_from_rows(settled_rows, prefix="production")
    challenger_metrics = _metrics_from_rows(settled_rows, prefix="challenger")
    settlement_id = _sha256_text(f"{snapshot['snapshot_id']}|settlement|v{SHADOW_SCHEMA_VERSION}")[:24]
    payload = {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "record_type": "shadow_settlement",
        "settlement_id": settlement_id,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_content_sha256": snapshot["content_sha256"],
        "season": snapshot["season"],
        "week": snapshot["week"],
        "checkpoint": snapshot["checkpoint"],
        "league_key": snapshot.get("league_key"),
        "settled_at": _utc_iso(settled_at or datetime.now(UTC)),
        "data_mode": "SETTLED_LIVE_SHADOW",
        "authority": "evaluation_only",
        "source_metadata": dict(source_metadata or {}),
        "forecast_count": len(forecast_rows),
        "settled_count": len(settled_rows),
        "missing_player_ids": missing_players,
        "complete": not missing_players,
        "metrics": {
            "production": production_metrics,
            "challenger": challenger_metrics,
        },
        "rows": settled_rows,
    }
    return _with_digest(payload)


class ShadowSeasonStore:
    """Immutable checkpoint + settlement store for live shadow-season evidence."""

    def __init__(self, root: str | Path = "artifacts/shadow_season") -> None:
        self.root = Path(root)
        self.snapshot_root = self.root / "snapshots"
        self.settlement_root = self.root / "settlements"

    def snapshot_path(self, snapshot: Mapping[str, object]) -> Path:
        return (
            self.snapshot_root
            / str(snapshot["season"])
            / f"week_{int(snapshot['week']):02d}"
            / str(snapshot["checkpoint"])
            / f"{snapshot['snapshot_id']}.json"
        )

    def settlement_path(self, snapshot_id: str) -> Path:
        return self.settlement_root / f"{snapshot_id}.json"

    @staticmethod
    def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _load(path: Path, *, label: str) -> dict[str, object]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{label} is not a JSON object: {path}")
        _verify_digest(payload, label=label)
        return payload

    def save_snapshot(self, snapshot: Mapping[str, object]) -> bool:
        _verify_digest(snapshot, label="shadow snapshot")
        path = self.snapshot_path(snapshot)
        if path.exists():
            existing = self._load(path, label="existing shadow snapshot")
            if existing["content_sha256"] == snapshot["content_sha256"]:
                return False
            raise ValueError(
                f"Immutable shadow checkpoint conflict for {snapshot['snapshot_id']}: {path}"
            )
        self._atomic_write(path, snapshot)
        return True

    def load_snapshot(self, snapshot_id: str) -> dict[str, object]:
        matches = list(self.snapshot_root.rglob(f"{snapshot_id}.json")) if self.snapshot_root.exists() else []
        if not matches:
            raise FileNotFoundError(f"Shadow snapshot unavailable: {snapshot_id}")
        if len(matches) > 1:
            raise ValueError(f"Shadow snapshot_id is not unique: {snapshot_id}")
        return self._load(matches[0], label="shadow snapshot")

    def save_settlement(self, settlement: Mapping[str, object]) -> bool:
        _verify_digest(settlement, label="shadow settlement")
        snapshot_id = str(settlement["snapshot_id"])
        snapshot = self.load_snapshot(snapshot_id)
        if str(settlement.get("snapshot_content_sha256")) != str(snapshot.get("content_sha256")):
            raise ValueError("Settlement references a different snapshot digest")
        path = self.settlement_path(snapshot_id)
        if path.exists():
            existing = self._load(path, label="existing shadow settlement")
            if existing["content_sha256"] == settlement["content_sha256"]:
                return False
            raise ValueError(f"Immutable shadow settlement conflict for {snapshot_id}: {path}")
        self._atomic_write(path, settlement)
        return True

    def snapshots(self, *, season: int | None = None) -> list[dict[str, object]]:
        root = self.snapshot_root / str(season) if season is not None else self.snapshot_root
        if not root.exists():
            return []
        return [self._load(path, label="shadow snapshot") for path in sorted(root.rglob("*.json"))]

    def settlements(self) -> list[dict[str, object]]:
        if not self.settlement_root.exists():
            return []
        return [
            self._load(path, label="shadow settlement")
            for path in sorted(self.settlement_root.glob("*.json"))
        ]

    def health(self, *, season: int | None = None) -> dict[str, object]:
        failures: list[str] = []
        snapshots: list[dict[str, object]] = []
        settlements: list[dict[str, object]] = []
        try:
            snapshots = self.snapshots(season=season)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"snapshot_integrity:{exc}")
        try:
            settlements = self.settlements()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"settlement_integrity:{exc}")
        snapshot_digests = {
            str(snapshot["snapshot_id"]): str(snapshot["content_sha256"])
            for snapshot in snapshots
        }
        for settlement in settlements:
            snapshot_id = str(settlement.get("snapshot_id"))
            if season is not None and int(settlement.get("season", -1)) != int(season):
                continue
            if snapshot_id not in snapshot_digests:
                failures.append(f"orphan_settlement:{snapshot_id}")
            elif str(settlement.get("snapshot_content_sha256")) != snapshot_digests[snapshot_id]:
                failures.append(f"settlement_snapshot_digest_mismatch:{snapshot_id}")
        return {
            "root": self.root.as_posix(),
            "season": season,
            "integrity_verified": not failures,
            "integrity_failures": failures,
            "snapshot_count": len(snapshots),
            "settlement_count": sum(
                1
                for settlement in settlements
                if season is None or int(settlement.get("season", -1)) == int(season)
            ),
        }

    def summary(self, *, season: int | None = None) -> dict[str, object]:
        snapshots = self.snapshots(season=season)
        settlements = [
            settlement
            for settlement in self.settlements()
            if season is None or int(settlement.get("season", -1)) == int(season)
        ]
        settlement_by_snapshot = {
            str(settlement["snapshot_id"]): settlement for settlement in settlements
        }
        all_rows: list[dict[str, object]] = []
        by_checkpoint: list[dict[str, object]] = []
        for checkpoint in SHADOW_CHECKPOINTS:
            checkpoint_snapshots = [
                snapshot for snapshot in snapshots if snapshot.get("checkpoint") == checkpoint
            ]
            checkpoint_settlements = [
                settlement_by_snapshot[str(snapshot["snapshot_id"])]
                for snapshot in checkpoint_snapshots
                if str(snapshot["snapshot_id"]) in settlement_by_snapshot
            ]
            rows = [
                dict(row)
                for settlement in checkpoint_settlements
                for row in (settlement.get("rows") or [])
            ]
            all_rows.extend(rows)
            by_checkpoint.append(
                {
                    "checkpoint": checkpoint,
                    "snapshots": len(checkpoint_snapshots),
                    "settled_snapshots": len(checkpoint_settlements),
                    "forecast_rows": sum(int(snapshot.get("forecast_count", 0)) for snapshot in checkpoint_snapshots),
                    "settled_rows": len(rows),
                    "production": _metrics_from_rows(rows, prefix="production"),
                    "challenger": _metrics_from_rows(rows, prefix="challenger"),
                }
            )

        positions = sorted({str(row.get("position")) for row in all_rows if row.get("position")})
        by_position = []
        for position in positions:
            rows = [row for row in all_rows if str(row.get("position")) == position]
            by_position.append(
                {
                    "position": position,
                    "n": len(rows),
                    "production": _metrics_from_rows(rows, prefix="production"),
                    "challenger": _metrics_from_rows(rows, prefix="challenger"),
                }
            )
        return {
            "data_mode": "LIVE_SHADOW" if snapshots else "UNAVAILABLE",
            "authority": {
                "production": "direct_player_quantile_model",
                "challenger": "research_only",
                "promotion_is_automatic": False,
                "settlement_is_evaluation_only": True,
            },
            "health": self.health(season=season),
            "season": season,
            "snapshot_count": len(snapshots),
            "settlement_count": len(settlements),
            "overall": {
                "production": _metrics_from_rows(all_rows, prefix="production"),
                "challenger": _metrics_from_rows(all_rows, prefix="challenger"),
            },
            "by_checkpoint": by_checkpoint,
            "by_position": by_position,
            "unsettled_snapshot_ids": [
                str(snapshot["snapshot_id"])
                for snapshot in snapshots
                if str(snapshot["snapshot_id"]) not in settlement_by_snapshot
            ],
        }
