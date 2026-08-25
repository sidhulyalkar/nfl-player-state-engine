from __future__ import annotations

import argparse
import hashlib
import io
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from player_state_engine.data.historical import canonicalize_injuries
from player_state_engine.evaluation.historical_sources import _kickoff_cutoffs

_AUTHORITY = "prospective_shadow_evidence_only"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _download(url: str, *, timeout: int = 180) -> bytes | None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "nfl-player-state-engine/prospective-availability-shadow"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _utc(value: datetime | str | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp


def _team_games(schedules: pd.DataFrame, *, season: int, week: int) -> pd.DataFrame:
    required = {"season", "week", "game_id", "home_team", "away_team"}
    missing = required - set(schedules.columns)
    if missing:
        raise ValueError(f"Schedule source is missing columns: {sorted(missing)}")

    games = schedules.copy()
    games["season"] = pd.to_numeric(games["season"], errors="coerce")
    games["week"] = pd.to_numeric(games["week"], errors="coerce")
    games = games.loc[games["season"].eq(season) & games["week"].eq(week)].copy()
    if "game_type" in games.columns:
        games = games.loc[games["game_type"].astype(str).str.upper().eq("REG")].copy()
    if games.empty:
        raise ValueError(f"No regular-season schedule rows found for {season=} {week=}")

    cutoffs = _kickoff_cutoffs(games, hours_before=1.5)
    games["game_id"] = games["game_id"].astype(str)
    games = games.merge(cutoffs, on="game_id", how="left", validate="one_to_one")
    if games["prediction_cutoff"].isna().any():
        raise ValueError("Prospective slate contains a game without a prediction cutoff")

    home = games[["season", "week", "game_id", "home_team", "prediction_cutoff"]].rename(
        columns={"home_team": "recent_team"}
    )
    away = games[["season", "week", "game_id", "away_team", "prediction_cutoff"]].rename(
        columns={"away_team": "recent_team"}
    )
    teams = pd.concat([home, away], ignore_index=True)
    if teams.duplicated(["season", "week", "recent_team"]).any():
        raise ValueError("Schedule contains multiple games for one team/week")
    return teams


def _latest_current_week_rows(
    injuries: pd.DataFrame,
    *,
    season: int,
    week: int,
    collected_at_utc: pd.Timestamp,
) -> pd.DataFrame:
    canonical = canonicalize_injuries(injuries).reset_index(drop=False).rename(
        columns={"index": "source_row_index"}
    )
    canonical = canonical.loc[
        canonical["season"].eq(season) & canonical["week"].eq(week)
    ].copy()
    canonical = canonical.loc[
        canonical["player_id"].notna() & canonical["recent_team"].notna()
    ].copy()
    if canonical.empty:
        return canonical

    # A source row can only be authoritative prospectively if it existed in the bytes we
    # actually collected. date_modified is retained as publisher metadata, but collection
    # time is the conservative availability timestamp used by the experiment.
    canonical["source_date_modified"] = pd.to_datetime(
        canonical["date_modified"], utc=True, errors="coerce"
    )
    canonical["_sort_modified"] = canonical["source_date_modified"].fillna(
        pd.Timestamp.min.tz_localize("UTC")
    )
    canonical = canonical.sort_values(
        ["recent_team", "player_id", "_sort_modified", "source_row_index"]
    ).drop_duplicates(["recent_team", "player_id"], keep="last")
    canonical["source_collected_at_utc"] = collected_at_utc
    return canonical.drop(columns=["_sort_modified"])


def build_snapshot(
    injury_bytes: bytes,
    schedule_bytes: bytes,
    *,
    injury_url: str,
    schedule_url: str,
    schedule_commit: str,
    season: int,
    week: int,
    collected_at_utc: datetime | str | pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build one immutable prospective injury-report snapshot without outcome fields."""

    collected = _utc(collected_at_utc)
    injuries_raw = pd.read_csv(io.BytesIO(injury_bytes))
    schedules = pd.read_csv(io.BytesIO(schedule_bytes), low_memory=False)
    team_games = _team_games(schedules, season=season, week=week)
    latest = _latest_current_week_rows(
        injuries_raw,
        season=season,
        week=week,
        collected_at_utc=collected,
    )

    if latest.empty:
        snapshot = pd.DataFrame(
            columns=[
                "season",
                "week",
                "game_id",
                "recent_team",
                "player_id",
                "player_name",
                "position",
                "report_status",
                "practice_status",
                "primary_injury",
                "source_date_modified",
                "source_collected_at_utc",
                "prediction_cutoff",
                "usable_before_cutoff",
            ]
        )
    else:
        snapshot = latest.merge(
            team_games,
            on=["season", "week", "recent_team"],
            how="inner",
            validate="many_to_one",
        )
        snapshot["usable_before_cutoff"] = snapshot["source_collected_at_utc"].le(
            snapshot["prediction_cutoff"]
        )
        keep = [
            "season",
            "week",
            "game_id",
            "recent_team",
            "player_id",
            "player_name",
            "position",
            "report_status",
            "practice_status",
            "primary_injury",
            "source_date_modified",
            "source_collected_at_utc",
            "prediction_cutoff",
            "usable_before_cutoff",
        ]
        snapshot = snapshot[keep].sort_values(["game_id", "recent_team", "player_id"])

    injury_sha = _sha256_bytes(injury_bytes)
    schedule_sha = _sha256_bytes(schedule_bytes)
    snapshot["source_url"] = injury_url
    snapshot["source_sha256"] = injury_sha
    snapshot["schedule_url"] = schedule_url
    snapshot["schedule_sha256"] = schedule_sha
    snapshot["schedule_commit"] = schedule_commit
    snapshot["authority"] = _AUTHORITY
    snapshot["production_feature_enabled"] = False

    manifest: dict[str, object] = {
        "schema_version": 1,
        "authority": _AUTHORITY,
        "automatic_promotion": False,
        "production_feature_enabled": False,
        "contains_player_outcomes": False,
        "season": int(season),
        "week": int(week),
        "collected_at_utc": collected.isoformat(),
        "prediction_cutoff_hours_before_kickoff": 1.5,
        "injury_source": {
            "url": injury_url,
            "bytes": len(injury_bytes),
            "sha256": injury_sha,
        },
        "schedule_source": {
            "url": schedule_url,
            "commit": schedule_commit,
            "bytes": len(schedule_bytes),
            "sha256": schedule_sha,
        },
        "rows": int(len(snapshot)),
        "usable_before_cutoff_rows": int(snapshot["usable_before_cutoff"].sum())
        if not snapshot.empty
        else 0,
        "games": int(snapshot["game_id"].nunique()) if not snapshot.empty else 0,
        "players": int(snapshot["player_id"].nunique()) if not snapshot.empty else 0,
        "availability_semantics": (
            "source_collected_at_utc is the authoritative availability timestamp. "
            "A row captured after its game prediction cutoff is retained for audit but may not "
            "enter prospective confirmation features for that game."
        ),
    }
    return snapshot.reset_index(drop=True), manifest


def persist_snapshot(
    snapshot: pd.DataFrame,
    manifest: dict[str, object],
    injury_bytes: bytes,
    *,
    output_root: Path,
) -> Path:
    collected = _utc(str(manifest["collected_at_utc"]))
    injury_sha = str(manifest["injury_source"]["sha256"])
    stamp = collected.strftime("%Y%m%dT%H%M%SZ")
    destination = (
        output_root
        / f"season_{int(manifest['season'])}"
        / f"week_{int(manifest['week']):02d}"
        / f"{stamp}_{injury_sha[:12]}"
    )
    if destination.exists():
        raise FileExistsError(f"Prospective snapshot already exists: {destination}")
    destination.mkdir(parents=True)

    # Preserve the exact mutable injury bytes. The schedule itself is commit-pinned and can be
    # rehydrated from schedule_url; the selected current-week cutoffs are persisted below.
    (destination / "injuries_source.csv").write_bytes(injury_bytes)
    snapshot.to_csv(destination / "availability_snapshot.csv", index=False)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return destination


def _write_unavailable_status(
    *,
    output_root: Path,
    season: int,
    week: int,
    injury_url: str,
    collected_at: pd.Timestamp,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"source_unavailable_{season}_w{week:02d}_{collected_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    payload = {
        "schema_version": 1,
        "authority": _AUTHORITY,
        "season": season,
        "week": week,
        "collected_at_utc": collected_at.isoformat(),
        "injury_source_url": injury_url,
        "status": "source_unavailable",
        "evidence_rows_created": 0,
        "production_feature_enabled": False,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Capture an immutable point-in-time injury-report snapshot for prospective research. "
            "Collection time, not publisher metadata, controls whether evidence is usable before "
            "a game's 1.5-hour prediction cutoff."
        )
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--injury-url", required=True)
    parser.add_argument("--schedule-url", required=True)
    parser.add_argument("--schedule-commit", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/prospective_availability_shadow"),
    )
    args = parser.parse_args()

    collected = pd.Timestamp(datetime.now(UTC))
    injury_bytes = _download(args.injury_url)
    if injury_bytes is None:
        path = _write_unavailable_status(
            output_root=args.output_root,
            season=args.season,
            week=args.week,
            injury_url=args.injury_url,
            collected_at=collected,
        )
        print(path)
        return

    schedule_bytes = _download(args.schedule_url)
    if schedule_bytes is None:
        raise ValueError("Commit-pinned schedule URL returned 404")

    snapshot, manifest = build_snapshot(
        injury_bytes,
        schedule_bytes,
        injury_url=args.injury_url,
        schedule_url=args.schedule_url,
        schedule_commit=args.schedule_commit,
        season=args.season,
        week=args.week,
        collected_at_utc=collected,
    )
    destination = persist_snapshot(
        snapshot,
        manifest,
        injury_bytes,
        output_root=args.output_root,
    )
    print(destination)
    print(json.dumps(manifest, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
