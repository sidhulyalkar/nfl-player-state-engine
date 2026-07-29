from __future__ import annotations

import hashlib
import json
import urllib.request
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

RELEASE = "https://github.com/nflverse/nflverse-data/releases/download"


def source_urls(seasons: Iterable[int]) -> dict[str, str]:
    years = sorted(set(int(s) for s in seasons))
    urls: dict[str, str] = {
        "combine": f"{RELEASE}/combine/combine.csv",
        "draft_picks": f"{RELEASE}/draft_picks/draft_picks.csv",
    }
    for season in years:
        urls[f"snap_counts_{season}"] = f"{RELEASE}/snap_counts/snap_counts_{season}.csv"
        urls[f"participation_{season}"] = (
            f"{RELEASE}/pbp_participation/pbp_participation_{season}.parquet"
        )
        urls[f"injuries_{season}"] = f"{RELEASE}/injuries/injuries_{season}.csv"
        urls[f"depth_charts_{season}"] = f"{RELEASE}/depth_charts/depth_charts_{season}.rds"
        urls[f"weekly_rosters_{season}"] = f"{RELEASE}/weekly_rosters/roster_weekly_{season}.csv"
        urls[f"pbp_{season}"] = f"{RELEASE}/pbp/play_by_play_{season}.parquet"
    return urls


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def acquire_historical_sources(
    seasons: Iterable[int],
    output_dir: str | Path,
    *,
    include_participation: bool = True,
    include_pbp: bool = True,
    continue_on_error: bool = True,
) -> pd.DataFrame:
    """Download immutable public source files with a checksum manifest.

    The downloader follows ordinary HTTPS redirects and does not use browser
    sessions, credentials, CAPTCHA bypass, or login circumvention.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    urls = source_urls(seasons)
    rows = []
    for name, url in urls.items():
        if not include_participation and name.startswith("participation_"):
            continue
        if not include_pbp and name.startswith("pbp_"):
            continue
        suffix = Path(url.split("?")[0]).suffix
        path = output_dir / f"{name}{suffix}"
        try:
            if not path.exists():
                request = urllib.request.Request(
                    url, headers={"User-Agent": "nfl-player-state-engine/0.5"}
                )
                with (
                    urllib.request.urlopen(request, timeout=180) as response,
                    path.open("wb") as target,
                ):
                    while chunk := response.read(1024 * 1024):
                        target.write(chunk)
            rows.append(
                {
                    "name": name,
                    "url": url,
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                    "status": "available",
                }
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "name": name,
                    "url": url,
                    "path": str(path),
                    "bytes": 0,
                    "sha256": "",
                    "status": f"unavailable: {type(exc).__name__}: {exc}",
                }
            )
            if not continue_on_error:
                raise
    manifest = pd.DataFrame(rows)
    manifest.to_csv(output_dir / "SOURCE_MANIFEST.csv", index=False)
    (output_dir / "SOURCE_MANIFEST.json").write_text(json.dumps(rows, indent=2))
    return manifest


def canonicalize_snap_counts(frame: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "player_id": ("pfr_player_id", "player_id", "gsis_id"),
        "player_name": ("player", "player_name"),
        "season": ("season",),
        "week": ("week",),
        "recent_team": ("team", "recent_team"),
        "position": ("position",),
        "snap_count": ("offense_snaps", "offensive_snaps", "snap_count"),
        "snap_share": ("offense_pct", "offensive_snap_pct", "snap_share"),
    }
    out = pd.DataFrame(index=frame.index)
    for target, candidates in aliases.items():
        source = next((c for c in candidates if c in frame), None)
        out[target] = frame[source] if source else pd.NA
    out["season"] = pd.to_numeric(out["season"], errors="coerce")
    out["week"] = pd.to_numeric(out["week"], errors="coerce")
    out["snap_count"] = pd.to_numeric(out["snap_count"], errors="coerce")
    if out["snap_share"].dtype == object:
        out["snap_share"] = out["snap_share"].astype(str).str.rstrip("%")
    out["snap_share"] = pd.to_numeric(out["snap_share"], errors="coerce")
    if out["snap_share"].dropna().median() > 1.5:
        out["snap_share"] /= 100.0
    return out


def aggregate_pass_play_participation(
    participation: pd.DataFrame, pbp: pd.DataFrame
) -> pd.DataFrame:
    """Build public pass-play participation proxy from players on the field.

    This is intentionally named a proxy: being on the field during a dropback
    does not prove a player ran a route, because backs and tight ends can block.
    """
    p = participation.copy()
    game_col = "nflverse_game_id" if "nflverse_game_id" in p else "game_id"
    required = {game_col, "play_id", "possession_team", "offense_players"}
    missing = required - set(p)
    if missing:
        raise ValueError(f"Participation table missing: {sorted(missing)}")
    pbp_game = "game_id" if "game_id" in pbp else "nflverse_game_id"
    columns = [pbp_game, "play_id", "season", "week"]
    for column in ("pass_attempt", "qb_dropback", "play_type"):
        if column in pbp:
            columns.append(column)
    merged = p.merge(
        pbp[columns], left_on=[game_col, "play_id"], right_on=[pbp_game, "play_id"], how="inner"
    )
    dropback = (
        pd.to_numeric(merged.get("qb_dropback", merged.get("pass_attempt", 0)), errors="coerce")
        .fillna(0)
        .gt(0)
    )
    if "play_type" in merged:
        dropback |= merged["play_type"].eq("pass")
    merged = merged.loc[dropback].copy()
    players = merged["offense_players"].fillna("").astype(str).str.replace(";", ",").str.split(",")
    exploded = merged.assign(player_id=players).explode("player_id")
    exploded["player_id"] = exploded["player_id"].astype(str).str.strip()
    exploded = exploded.loc[exploded["player_id"].ne("")]
    usage = (
        exploded.groupby(["season", "week", "possession_team", "player_id"], as_index=False)
        .size()
        .rename(columns={"possession_team": "recent_team", "size": "pass_play_participation_count"})
    )
    team_dropbacks = (
        merged.groupby(["season", "week", "possession_team"], as_index=False)
        .size()
        .rename(columns={"possession_team": "recent_team", "size": "team_dropbacks_proxy"})
    )
    usage = usage.merge(team_dropbacks, on=["season", "week", "recent_team"], how="left")
    usage["pass_play_participation_rate"] = usage["pass_play_participation_count"] / usage[
        "team_dropbacks_proxy"
    ].clip(lower=1)
    return usage


def _pick(frame: pd.DataFrame, candidates: tuple[str, ...]) -> pd.Series:
    """Coalesce schema aliases row by row.

    Historical releases are commonly concatenated before canonicalization. A
    simple "first column present" rule loses values when an old and new schema
    contribute different alias columns to the same concatenated frame.
    """
    present = [column for column in candidates if column in frame]
    if not present:
        return pd.Series(pd.NA, index=frame.index)
    if len(present) == 1:
        return frame[present[0]]
    return frame[present].bfill(axis=1).iloc[:, 0]


def _name_key(values: pd.Series) -> pd.Series:
    return (
        values.fillna("")
        .astype(str)
        .str.lower()
        .str.replace(r"[^a-z0-9 ]", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def canonicalize_weekly_rosters(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    out["player_id"] = _pick(frame, ("gsis_id", "player_id"))
    out["pfr_player_id"] = _pick(frame, ("pfr_id", "pfr_player_id"))
    out["player_name"] = _pick(frame, ("full_name", "player_name", "player"))
    out["season"] = pd.to_numeric(_pick(frame, ("season",)), errors="coerce")
    out["week"] = pd.to_numeric(_pick(frame, ("week",)), errors="coerce")
    out["recent_team"] = _pick(frame, ("team", "recent_team"))
    out["position"] = _pick(frame, ("position", "pos"))
    out["status"] = _pick(frame, ("status", "roster_status"))
    out["player_id"] = out["player_id"].astype("string")
    out["pfr_player_id"] = out["pfr_player_id"].astype("string")
    out["name_key"] = _name_key(out["player_name"])
    return out


def canonicalize_injuries(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    out["season"] = pd.to_numeric(_pick(frame, ("season",)), errors="coerce")
    out["week"] = pd.to_numeric(_pick(frame, ("week",)), errors="coerce")
    out["player_id"] = _pick(frame, ("gsis_id", "player_id")).astype("string")
    out["player_name"] = _pick(frame, ("full_name", "player_name"))
    out["recent_team"] = _pick(frame, ("team", "recent_team"))
    out["position"] = _pick(frame, ("position", "pos"))
    out["report_status"] = _pick(frame, ("report_status", "game_status")).astype("string")
    out["practice_status"] = _pick(frame, ("practice_status", "practice_participation")).astype(
        "string"
    )
    for column in ("report_status", "practice_status"):
        out[column] = (
            out[column].str.strip().str.lower().replace({"": pd.NA, "nan": pd.NA, "<na>": pd.NA})
        )
    out["primary_injury"] = _pick(
        frame, ("report_primary_injury", "practice_primary_injury", "primary_injury")
    )
    out["date_modified"] = pd.to_datetime(
        _pick(frame, ("date_modified", "updated_at", "observed_at")), utc=True, errors="coerce"
    )
    report_map = {
        "out": 0.0,
        "doubtful": 0.20,
        "questionable": 0.72,
        "probable": 0.93,
    }
    practice_map = {
        "did not participate": 0.35,
        "dnp": 0.35,
        "limited participation": 0.72,
        "limited": 0.72,
        "full participation": 0.97,
        "full": 0.97,
    }
    report_present = out["report_status"].notna()
    practice_present = out["practice_status"].notna()
    out["official_report_availability_prior"] = (
        out["report_status"].map(report_map).where(report_present)
    )
    out.loc[
        report_present & out["official_report_availability_prior"].isna(),
        "official_report_availability_prior",
    ] = 0.85
    out["official_practice_availability_prior"] = (
        out["practice_status"].map(practice_map).where(practice_present)
    )
    out.loc[
        practice_present & out["official_practice_availability_prior"].isna(),
        "official_practice_availability_prior",
    ] = 0.85
    evidence_present = report_present | practice_present
    out["official_availability_prior"] = pd.concat(
        [
            out["official_report_availability_prior"].fillna(1.0),
            out["official_practice_availability_prior"].fillna(1.0),
        ],
        axis=1,
    ).min(axis=1)
    out["official_availability_prior"] = out["official_availability_prior"].where(evidence_present)
    out["official_injury_evidence_present"] = evidence_present.astype(int)
    return out


def canonicalize_depth_charts(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    observed_at = pd.to_datetime(
        _pick(frame, ("dt", "observed_at", "date_modified")),
        utc=True,
        errors="coerce",
    )
    out["observed_at"] = observed_at
    out["season"] = pd.to_numeric(_pick(frame, ("season",)), errors="coerce")
    inferred_season = observed_at.dt.year.where(observed_at.dt.month.gt(3), observed_at.dt.year - 1)
    out["season"] = out["season"].fillna(inferred_season)
    out["week"] = pd.to_numeric(_pick(frame, ("week",)), errors="coerce")
    out["player_id"] = _pick(frame, ("gsis_id", "player_id")).astype("string")
    out["player_name"] = _pick(frame, ("full_name", "player_name", "player"))
    out["recent_team"] = _pick(frame, ("team", "recent_team", "club_code"))
    out["position"] = _pick(frame, ("position", "pos", "position_group"))
    out["depth_position"] = _pick(frame, ("depth_position", "depth_chart_position", "position"))
    out["depth_rank"] = pd.to_numeric(
        _pick(
            frame,
            ("depth_team", "depth_rank", "depth_chart_order", "rank", "pos_rank"),
        ),
        errors="coerce",
    )
    out["formation"] = _pick(frame, ("formation",))
    out["name_key"] = _name_key(out["player_name"])
    weekly = out["season"].notna() & out["week"].notna() & out["depth_rank"].notna()
    timestamped = (
        out["season"].notna()
        & out["observed_at"].notna()
        & out["recent_team"].notna()
        & out["depth_rank"].notna()
    )
    out["schema_status"] = np.select(
        [weekly, timestamped],
        ["supported_weekly", "supported_timestamped"],
        default="unsupported_schema",
    )
    return out


def resolve_snap_player_ids(
    snap_counts: pd.DataFrame, weekly_rosters: pd.DataFrame
) -> pd.DataFrame:
    """Resolve PFR snap-count rows to GSIS IDs with an auditable match method."""
    snaps = canonicalize_snap_counts(snap_counts).reset_index(drop=True)
    snaps["_snap_row_id"] = np.arange(len(snaps))
    snaps["name_key"] = _name_key(snaps["player_name"])
    snaps = snaps.rename(columns={"player_id": "snap_source_player_id"})
    if "gsis_id" in snap_counts:
        snaps["source_gsis_id"] = snap_counts.reset_index(drop=True)["gsis_id"].astype("string")
    else:
        snaps["source_gsis_id"] = pd.Series(pd.NA, index=snaps.index, dtype="string")
    snaps["pfr_player_id"] = _pick(
        snap_counts.reset_index(drop=True), ("pfr_player_id", "pfr_id")
    ).astype("string")
    snaps["pfr_player_id"] = snaps["pfr_player_id"].fillna(
        snaps["snap_source_player_id"].astype("string")
    )
    rosters = canonicalize_weekly_rosters(weekly_rosters)
    exact = rosters.dropna(subset=["pfr_player_id", "player_id"]).drop_duplicates(
        ["season", "week", "recent_team", "pfr_player_id"], keep="last"
    )
    out = snaps.merge(
        exact[["season", "week", "recent_team", "pfr_player_id", "player_id"]],
        on=["season", "week", "recent_team", "pfr_player_id"],
        how="left",
        validate="many_to_one",
    )
    direct_gsis = out["source_gsis_id"].notna()
    out.loc[direct_gsis, "player_id"] = out.loc[direct_gsis, "source_gsis_id"]
    out["id_match_method"] = np.select(
        [direct_gsis, out["player_id"].notna()],
        ["source_gsis", "pfr_crosswalk"],
        default="unmatched",
    )

    fallback = rosters.dropna(subset=["player_id"]).copy()
    fallback_counts = fallback.groupby(["season", "week", "recent_team", "name_key"], dropna=False)[
        "player_id"
    ].transform("nunique")
    fallback = fallback.loc[fallback_counts.eq(1)].drop_duplicates(
        ["season", "week", "recent_team", "name_key"], keep="last"
    )
    missing = out["player_id"].isna()
    if missing.any():
        candidate = out.loc[
            missing, ["_snap_row_id", "season", "week", "recent_team", "name_key"]
        ].merge(
            fallback[["season", "week", "recent_team", "name_key", "player_id"]],
            on=["season", "week", "recent_team", "name_key"],
            how="left",
            validate="many_to_one",
        )
        fallback_ids = candidate.set_index("_snap_row_id")["player_id"]
        out.loc[missing, "player_id"] = out.loc[missing, "_snap_row_id"].map(fallback_ids)
        out.loc[missing & out["player_id"].notna(), "id_match_method"] = "name_team_week"
    out["player_id"] = out["player_id"].astype("string")
    return out.drop(columns=["_snap_row_id", "source_gsis_id"], errors="ignore")


def read_historical_table(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix == ".json":
        return pd.read_json(path)
    if suffix == ".rds":
        try:
            import pyreadr  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Reading RDS depth charts requires `pip install pyreadr`.") from exc
        result = pyreadr.read_r(str(path))
        if not result:
            raise ValueError(f"RDS file contained no data frame: {path}")
        return next(iter(result.values()))
    raise ValueError(f"Unsupported historical table: {path}")
