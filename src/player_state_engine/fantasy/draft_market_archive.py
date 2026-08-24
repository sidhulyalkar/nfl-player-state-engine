from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from player_state_engine.fantasy.rankings import (
    _normalize_name,
    _normalize_position,
    _normalize_team,
)

ARCHIVE_SCHEMA_VERSION = 1
RAW_FILES = ("draft.json", "picks.json", "traded_picks.json")
STARTER_SLOT_KEYS = (
    "slots_qb",
    "slots_rb",
    "slots_wr",
    "slots_te",
    "slots_flex",
    "slots_super_flex",
    "slots_superflex",
    "slots_k",
    "slots_def",
)


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_iso_from_millis(value: object) -> str | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(timestamp):
        return None
    try:
        return datetime.fromtimestamp(timestamp / 1000.0, tz=UTC).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _archive_dir(root: str | Path, draft: dict[str, Any]) -> Path:
    draft_id = str(draft.get("draft_id") or "").strip()
    if not draft_id:
        raise ValueError("Sleeper draft payload is missing draft_id")
    season = str(draft.get("season") or "unknown")
    return Path(root) / season / draft_id


def _verify_existing_archive(
    destination: Path,
    payloads: dict[str, bytes],
) -> dict[str, Any]:
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        existing = [name for name in RAW_FILES if (destination / name).exists()]
        if existing:
            raise ValueError(
                f"Incomplete immutable draft archive at {destination}; raw files exist without manifest"
            )
        raise FileNotFoundError(manifest_path)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid draft archive manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"Draft archive manifest must be an object: {manifest_path}")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError(f"Draft archive manifest is missing files table: {manifest_path}")

    for name, payload in payloads.items():
        path = destination / name
        record = files.get(name)
        if not path.is_file() or not isinstance(record, dict):
            raise ValueError(f"Draft archive is incomplete for {name}: {destination}")
        recorded_hash = str(record.get("sha256") or "")
        disk_hash = _sha256_file(path)
        incoming_hash = _sha256_bytes(payload)
        if not recorded_hash or disk_hash != recorded_hash:
            raise ValueError(f"Draft archive integrity failure for {path}")
        if incoming_hash != recorded_hash:
            raise ValueError(
                f"Sleeper draft payload changed for immutable archive {destination}; "
                "write a separate refresh archive instead of overwriting history"
            )
    return manifest


def archive_sleeper_draft(
    root: str | Path,
    *,
    draft: dict[str, Any],
    picks: list[dict[str, Any]],
    traded_picks: list[dict[str, Any]],
    retrieved_at: datetime | str | None = None,
    source_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Persist one Sleeper draft immutably and return its frozen manifest."""

    destination = _archive_dir(root, draft)
    payloads = {
        "draft.json": _json_bytes(draft),
        "picks.json": _json_bytes(picks),
        "traded_picks.json": _json_bytes(traded_picks),
    }
    if destination.exists():
        try:
            return _verify_existing_archive(destination, payloads)
        except FileNotFoundError:
            pass

    destination.mkdir(parents=True, exist_ok=True)
    if any((destination / name).exists() for name in RAW_FILES) or (
        destination / "manifest.json"
    ).exists():
        raise ValueError(f"Refusing to overwrite partial immutable archive: {destination}")

    captured = pd.Timestamp(retrieved_at or datetime.now(UTC))
    if captured.tzinfo is None:
        captured = captured.tz_localize("UTC")
    else:
        captured = captured.tz_convert("UTC")

    file_records: dict[str, dict[str, object]] = {}
    for name, payload in payloads.items():
        path = destination / name
        path.write_bytes(payload)
        file_records[name] = {
            "bytes": len(payload),
            "sha256": _sha256_bytes(payload),
        }

    draft_id = str(draft.get("draft_id"))
    league_id = draft.get("league_id")
    urls = source_urls or {
        "draft.json": f"https://api.sleeper.app/v1/draft/{draft_id}",
        "picks.json": f"https://api.sleeper.app/v1/draft/{draft_id}/picks",
        "traded_picks.json": f"https://api.sleeper.app/v1/draft/{draft_id}/traded_picks",
    }
    manifest: dict[str, Any] = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "authority": "raw_external_evidence",
        "platform": "sleeper",
        "draft_id": draft_id,
        "league_id": str(league_id) if league_id not in {None, ""} else None,
        "season": int(draft["season"]) if str(draft.get("season") or "").isdigit() else draft.get("season"),
        "status": draft.get("status"),
        "draft_type": draft.get("type"),
        "draft_started_at": _utc_iso_from_millis(draft.get("start_time")),
        "retrieved_at": captured.isoformat(),
        "files": file_records,
        "source_urls": urls,
    }
    (destination / "manifest.json").write_bytes(_json_bytes(manifest))
    return manifest


def load_archived_draft(directory: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read draft archive manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"Draft archive manifest must be an object: {manifest_path}")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError(f"Draft archive manifest missing files table: {manifest_path}")

    loaded: dict[str, object] = {}
    for name in RAW_FILES:
        path = directory / name
        record = files.get(name)
        if not path.is_file() or not isinstance(record, dict):
            raise ValueError(f"Draft archive is incomplete for {name}: {directory}")
        if _sha256_file(path) != str(record.get("sha256") or ""):
            raise ValueError(f"Draft archive integrity failure for {path}")
        loaded[name] = json.loads(path.read_text(encoding="utf-8"))

    draft = loaded["draft.json"]
    picks = loaded["picks.json"]
    traded = loaded["traded_picks.json"]
    if not isinstance(draft, dict) or not isinstance(picks, list) or not isinstance(traded, list):
        raise ValueError(f"Draft archive payload shapes are invalid: {directory}")
    return draft, [dict(item) for item in picks], [dict(item) for item in traded], manifest


def _starter_slots(settings: dict[str, Any]) -> int:
    total = 0
    seen_superflex = False
    for key in STARTER_SLOT_KEYS:
        if key in {"slots_super_flex", "slots_superflex"}:
            if seen_superflex:
                continue
            if key in settings:
                seen_superflex = True
        try:
            total += max(0, int(settings.get(key, 0) or 0))
        except (TypeError, ValueError):
            continue
    return total


def _superflex_slots(settings: dict[str, Any]) -> int:
    for key in ("slots_super_flex", "slots_superflex"):
        if key in settings:
            try:
                return max(0, int(settings.get(key, 0) or 0))
            except (TypeError, ValueError):
                return 0
    return 0


def normalize_sleeper_draft(
    draft: dict[str, Any],
    picks: list[dict[str, Any]],
    *,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Normalize a raw Sleeper draft without introducing market or football outcome fields."""

    settings = draft.get("settings") if isinstance(draft.get("settings"), dict) else {}
    metadata = draft.get("metadata") if isinstance(draft.get("metadata"), dict) else {}
    draft_id = str(draft.get("draft_id") or "")
    if not draft_id:
        raise ValueError("Sleeper draft payload is missing draft_id")
    draft_started_at = _utc_iso_from_millis(draft.get("start_time"))
    if draft_started_at is None:
        raise ValueError(f"Sleeper draft {draft_id} is missing a valid start_time")

    try:
        teams = int(settings.get("teams") or 0)
    except (TypeError, ValueError):
        teams = 0
    if teams < 2:
        raise ValueError(f"Sleeper draft {draft_id} has invalid team count {teams}")
    try:
        qb_slots = max(0, int(settings.get("slots_qb", 0) or 0))
    except (TypeError, ValueError):
        qb_slots = 0

    rows: list[dict[str, object]] = []
    for raw in picks:
        pick_no = pd.to_numeric(raw.get("pick_no"), errors="coerce")
        if pd.isna(pick_no) or float(pick_no) < 1 or not float(pick_no).is_integer():
            raise ValueError(f"Sleeper draft {draft_id} contains an invalid pick_no")
        pick_metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        first_name = str(pick_metadata.get("first_name") or "").strip()
        last_name = str(pick_metadata.get("last_name") or "").strip()
        player_name = str(
            raw.get("player_name")
            or pick_metadata.get("player_name")
            or " ".join(part for part in (first_name, last_name) if part)
        ).strip()
        position = raw.get("position") or pick_metadata.get("position")
        nfl_team = raw.get("nfl_team") or pick_metadata.get("team")
        platform_player_id = raw.get("platform_player_id") or raw.get("player_id")
        rows.append(
            {
                "draft_id": draft_id,
                "league_id": str(draft.get("league_id")) if draft.get("league_id") not in {None, ""} else None,
                "season": int(draft["season"]) if str(draft.get("season") or "").isdigit() else draft.get("season"),
                "draft_started_at": draft_started_at,
                "draft_type": draft.get("type"),
                "actual_pick": int(pick_no),
                "round": pd.to_numeric(raw.get("round"), errors="coerce"),
                "draft_slot": pd.to_numeric(raw.get("draft_slot"), errors="coerce"),
                "picked_by": str(raw.get("picked_by")) if raw.get("picked_by") not in {None, ""} else None,
                "roster_id": str(raw.get("roster_id")) if raw.get("roster_id") not in {None, ""} else None,
                "platform_player_id": str(platform_player_id) if platform_player_id not in {None, ""} else None,
                "canonical_player_id": raw.get("canonical_player_id"),
                "player_name": player_name or None,
                "position": _normalize_position(position),
                "nfl_team": _normalize_team(nfl_team),
                "teams": teams,
                "scoring": str(metadata.get("scoring_type") or "unknown").strip().lower(),
                "qb_slots_per_team": qb_slots,
                "superflex_slots_per_team": _superflex_slots(settings),
                "starter_slots_per_team": _starter_slots(settings),
                "source": "sleeper",
                "source_retrieved_at": retrieved_at,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    if frame["actual_pick"].duplicated().any():
        raise ValueError(f"Sleeper draft {draft_id} contains duplicate pick numbers")
    return frame.sort_values("actual_pick", kind="mergesort").reset_index(drop=True)


def normalize_archive(root: str | Path) -> tuple[pd.DataFrame, dict[str, object]]:
    root = Path(root)
    frames: list[pd.DataFrame] = []
    manifests = sorted(root.rglob("manifest.json")) if root.exists() else []
    for manifest_path in manifests:
        draft, picks, _, manifest = load_archived_draft(manifest_path.parent)
        frames.append(
            normalize_sleeper_draft(
                draft,
                picks,
                retrieved_at=str(manifest.get("retrieved_at") or "") or None,
            )
        )
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    report = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "authority": "normalized_external_evidence",
        "archive_root": str(root),
        "drafts": len(manifests),
        "picks": int(len(frame)),
    }
    return frame, report


def _ranking_identity_index(snapshot: pd.DataFrame) -> dict[str, object]:
    by_canonical: dict[str, list[int]] = {}
    by_name_position_team: dict[tuple[str, str, str], list[int]] = {}
    by_name_position: dict[tuple[str, str], list[int]] = {}
    for index, row in snapshot.iterrows():
        canonical = row.get("canonical_player_id")
        if canonical is not None and pd.notna(canonical) and str(canonical):
            by_canonical.setdefault(str(canonical), []).append(int(index))
        name = _normalize_name(row.get("player_name"))
        position = _normalize_position(row.get("position"))
        team = _normalize_team(row.get("nfl_team"))
        if name and position:
            by_name_position.setdefault((name, position), []).append(int(index))
            if team:
                by_name_position_team.setdefault((name, position, team), []).append(int(index))
    return {
        "canonical": by_canonical,
        "name_position_team": by_name_position_team,
        "name_position": by_name_position,
    }


def _match_ranking_row(
    pick: pd.Series,
    snapshot: pd.DataFrame,
    index: dict[str, object],
) -> tuple[pd.Series | None, str | None]:
    canonical = pick.get("canonical_player_id")
    canonical_map = index["canonical"]
    if canonical is not None and pd.notna(canonical) and str(canonical):
        candidates = canonical_map.get(str(canonical), [])  # type: ignore[union-attr]
        if len(candidates) == 1:
            return snapshot.loc[candidates[0]], "canonical_id"
        if len(candidates) > 1:
            return None, "ambiguous_canonical_id"

    name = _normalize_name(pick.get("player_name"))
    position = _normalize_position(pick.get("position"))
    team = _normalize_team(pick.get("nfl_team"))
    team_map = index["name_position_team"]
    if name and position and team:
        candidates = team_map.get((name, position, team), [])  # type: ignore[union-attr]
        if len(candidates) == 1:
            return snapshot.loc[candidates[0]], "name_position_team"
        if len(candidates) > 1:
            return None, "ambiguous_name_position_team"

    name_map = index["name_position"]
    if name and position:
        candidates = name_map.get((name, position), [])  # type: ignore[union-attr]
        if len(candidates) == 1:
            return snapshot.loc[candidates[0]], "name_position"
        if len(candidates) > 1:
            return None, "ambiguous_name_position"
    return None, "unmatched"


def asof_join_market_snapshots(
    draft_picks: pd.DataFrame,
    rankings: pd.DataFrame,
    *,
    source: str | None = None,
    ranking_type: str = "adp",
    max_snapshot_age_days: float | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Attach the latest pre-draft market snapshot without manufacturing missing ADP."""

    required_draft = {"draft_id", "draft_started_at", "player_name", "position"}
    missing_draft = sorted(required_draft - set(draft_picks.columns))
    if missing_draft:
        raise ValueError(f"Draft outcome table is missing columns: {missing_draft}")
    required_rank = {"source", "ranking_type", "captured_at_utc", "rank", "player_name", "position"}
    missing_rank = sorted(required_rank - set(rankings.columns))
    if missing_rank:
        raise ValueError(f"Market snapshot table is missing columns: {missing_rank}")
    if max_snapshot_age_days is not None and float(max_snapshot_age_days) <= 0:
        raise ValueError("max_snapshot_age_days must be positive when supplied")

    market = rankings.copy()
    market["captured_at_utc"] = pd.to_datetime(market["captured_at_utc"], errors="coerce", utc=True)
    market["rank"] = pd.to_numeric(market["rank"], errors="coerce")
    market = market.loc[
        market["captured_at_utc"].notna()
        & market["rank"].notna()
        & market["ranking_type"].astype(str).str.lower().eq(str(ranking_type).lower())
    ].copy()
    if source is not None:
        market = market.loc[market["source"].astype(str).str.lower().eq(str(source).lower())].copy()
    sources = sorted(set(market["source"].astype(str).str.lower()))
    if source is None and len(sources) > 1:
        raise ValueError(
            f"Multiple market sources are available {sources}; select one explicitly for a frozen as-of join"
        )

    output_groups: list[pd.DataFrame] = []
    matched = 0
    unmatched = 0
    ambiguous = 0
    drafts_with_snapshot = 0
    drafts_without_snapshot = 0

    for draft_id, group in draft_picks.groupby("draft_id", sort=False):
        data = group.copy()
        draft_times = pd.to_datetime(data["draft_started_at"], errors="coerce", utc=True).dropna()
        if draft_times.empty or draft_times.nunique() != 1:
            raise ValueError(f"Draft {draft_id!r} must have one valid draft_started_at")
        draft_time = draft_times.iloc[0]
        eligible = market.loc[market["captured_at_utc"] <= draft_time].copy()
        if max_snapshot_age_days is not None:
            minimum = draft_time - pd.Timedelta(days=float(max_snapshot_age_days))
            eligible = eligible.loc[eligible["captured_at_utc"] >= minimum]
        if eligible.empty:
            drafts_without_snapshot += 1
            data["market_adp"] = np.nan
            data["market_adp_sd"] = np.nan
            data["market_snapshot_at"] = pd.NaT
            data["market_source"] = None
            data["market_identity_match_method"] = "no_pre_draft_snapshot"
            data["point_in_time_market_verified"] = False
            output_groups.append(data)
            unmatched += len(data)
            continue

        latest = eligible["captured_at_utc"].max()
        snapshot = eligible.loc[eligible["captured_at_utc"].eq(latest)].copy().reset_index(drop=True)
        source_values = sorted(set(snapshot["source"].astype(str).str.lower()))
        if len(source_values) != 1:
            raise ValueError(
                f"Draft {draft_id!r} has multiple sources at the selected as-of timestamp; choose source explicitly"
            )
        drafts_with_snapshot += 1
        identity_index = _ranking_identity_index(snapshot)
        records: list[dict[str, object]] = []
        for _, pick in data.iterrows():
            record = pick.to_dict()
            matched_row, method = _match_ranking_row(pick, snapshot, identity_index)
            record["market_snapshot_at"] = latest
            record["market_source"] = source_values[0]
            record["market_identity_match_method"] = method
            record["market_scoring"] = None
            record["market_teams"] = np.nan
            record["market_qb_format"] = None
            if matched_row is None:
                record["market_adp"] = np.nan
                record["market_adp_sd"] = np.nan
                record["point_in_time_market_verified"] = False
                unmatched += 1
                if method and method.startswith("ambiguous"):
                    ambiguous += 1
            else:
                record["market_adp"] = float(matched_row["rank"])
                rank_std = pd.to_numeric(matched_row.get("rank_std"), errors="coerce")
                record["market_adp_sd"] = float(rank_std) if pd.notna(rank_std) else np.nan
                record["market_scoring"] = str(matched_row.get("scoring") or "unknown").lower()
                teams_value = pd.to_numeric(matched_row.get("teams"), errors="coerce")
                record["market_teams"] = float(teams_value) if pd.notna(teams_value) else np.nan
                record["market_qb_format"] = str(matched_row.get("qb_format") or "unknown").lower()
                record["point_in_time_market_verified"] = True
                matched += 1
            records.append(record)
        output_groups.append(pd.DataFrame(records))

    joined = pd.concat(output_groups, ignore_index=True) if output_groups else draft_picks.copy()
    if not joined.empty:
        joined["market_snapshot_at"] = pd.to_datetime(
            joined["market_snapshot_at"], errors="coerce", utc=True
        )
        joined["draft_started_at"] = pd.to_datetime(
            joined["draft_started_at"], errors="coerce", utc=True
        )
        bad_time = (
            joined["point_in_time_market_verified"].fillna(False).astype(bool)
            & (joined["market_snapshot_at"] > joined["draft_started_at"])
        )
        if bool(bad_time.any()):
            raise AssertionError("As-of market join produced post-draft market evidence")

    total = int(len(joined))
    report = {
        "schema_version": 1,
        "authority": "joined_external_evidence",
        "ranking_type": str(ranking_type).lower(),
        "source": source or (sources[0] if len(sources) == 1 else None),
        "drafts": int(draft_picks["draft_id"].astype(str).nunique()) if not draft_picks.empty else 0,
        "drafts_with_pre_draft_snapshot": drafts_with_snapshot,
        "drafts_without_pre_draft_snapshot": drafts_without_snapshot,
        "rows": total,
        "matched_rows": matched,
        "unmatched_rows": unmatched,
        "ambiguous_identity_rows": ambiguous,
        "verified_rate": float(matched / total) if total else 0.0,
        "max_snapshot_age_days": max_snapshot_age_days,
        "missing_market_is_never_imputed_from_actual_pick": True,
    }
    return joined, report
