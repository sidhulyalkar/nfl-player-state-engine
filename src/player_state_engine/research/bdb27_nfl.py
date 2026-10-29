"""Research-only 2027 rookie NFL movement adapter and Combine linkage audit.

No raw files downloaded. Game frames are filtered to rookie *regular season*
for the sampled Combine players, then grouped by play. In-game heading is not
helmet direction, and player trajectories contain neither gaze nor plant forces.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .bdb27_qualification import (
    QualificationConfig, _header, _local_file, _prepare_players, source_digest,
)
from .bilateral import asymmetry_profiles, extract_turn_events, tag_event_field_sides

GAME_KEYS = frozenset({"nfl_id", "game_id", "play_id", "x", "y"})
GAMES_KEYS = frozenset({"game_id", "season", "season_type"})


def canonical_rookie_game(
    tracking: pd.DataFrame, games: pd.DataFrame, players: pd.DataFrame,
    config: QualificationConfig, *, position: str = "DB",
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Converts a **complete** source subset of game frames, without inventing field side.

    `frame_id` or `time` required. `independent_trial_id` groups a full play,
    even when discontinuities yield multiple continuous analysis segments.
    """
    if position not in {"DB", "WR", "TE", "OL", "DL"}:
        raise ValueError("unsupported position")
    if not GAME_KEYS.issubset(tracking.columns) or not GAMES_KEYS.issubset(games.columns):
        raise ValueError("NFL game tracking/game metadata schema mismatch")
    if "frame_id" not in tracking.columns and "time" not in tracking.columns:
        raise ValueError("NFL tracking requires frame_id or time")
    p = _prepare_players(players)
    p = p.loc[p.combine_position.eq(position)].copy()
    g = games[["game_id", "season", "season_type"]].copy()
    if g.game_id.isna().any() or g.game_id.duplicated().any():
        raise ValueError("games.csv duplicate/null game identifier")
    g["season"] = pd.to_numeric(g.season, errors="coerce")
    if g.season.isna().any():
        raise ValueError("games.csv season is invalid")
    df = tracking.copy()
    # Ball and unassigned tracking rows can have no player identifier.
    # Do not mistake those for missing player attributes; they are excluded
    # from individual-player movement analysis before the strict key check.
    non_player_rows = int(df.nfl_id.isna().sum())
    df = df.loc[df.nfl_id.notna()].copy()
    if df[list(GAME_KEYS)].isna().any().any():
        raise ValueError("null critical NFL player tracking identities or coordinates")
    df["nfl_id"] = df.nfl_id.astype("string").str.replace(r"\.0+$", "", regex=True)
    df = df.merge(g, on="game_id", how="left", validate="many_to_one", indicator=True)
    if (df._merge != "both").any():
        raise ValueError("NFL tracking has game IDs missing from games.csv")
    df = df.drop(columns="_merge")
    df = df.merge(p[["nfl_id", "combine_position", "draft_year"]], on="nfl_id", how="inner", validate="many_to_one")
    eligible = df.loc[(df.season == df.draft_year) & df.season_type.eq("REG")].copy()
    if eligible.empty:
        raise ValueError("no valid rookie regular-season tracking frames for selected position")
    for name in ("x", "y"):
        eligible[name] = pd.to_numeric(eligible[name], errors="coerce")
        if not np.isfinite(eligible[name].to_numpy(dtype=float)).all():
            raise ValueError(f"invalid NFL tracking coordinate {name}")
    if (eligible.y < 0).any() or (eligible.y > 160 / 3 + 0.1).any():
        raise ValueError("NFL Y coordinates outside assumed 53.33-yard field")
    if "frame_id" in eligible.columns:
        eligible["source_frame"] = pd.to_numeric(eligible.frame_id, errors="coerce")
    else:
        eligible["source_frame"] = np.nan
    if eligible.source_frame.notna().all():
        if (eligible.source_frame % 1 != 0).any():
            raise ValueError("non-integral NFL frame_id")
    elif "time" not in eligible.columns:
        raise ValueError("NFL frame_id missing and no time available")
    else:
        eligible["source_frame"] = np.nan
    if "time" in eligible.columns:
        eligible["timestamp"] = pd.to_datetime(eligible.time, errors="coerce", utc=True, format="mixed")
    else:
        eligible["timestamp"] = pd.NaT
    if eligible.source_frame.isna().all() and eligible.timestamp.isna().any():
        raise ValueError("NFL timestamps cannot be parsed")
    keys = ["season", "game_id", "play_id", "nfl_id"]
    sort_key = "source_frame" if eligible.source_frame.notna().all() else "timestamp"
    if eligible.duplicated(keys + [sort_key]).any():
        raise ValueError("duplicate frame within NFL player-play")
    eligible = eligible.sort_values(keys + [sort_key], kind="mergesort")
    out: list[pd.DataFrame] = []
    coverage: list[dict] = []
    rejected_gaps = 0
    for key, play in eligible.groupby(keys, sort=False):
        play = play.reset_index(drop=True)
        frames = play.source_frame.to_numpy(dtype=float)
        if np.isfinite(frames).all():
            breaks = np.diff(frames) != 1
            times = (frames - frames[0]) / config.nominal_hz
        else:
            times = (play.timestamp - play.timestamp.iloc[0]).dt.total_seconds().to_numpy(dtype=float)
            breaks = np.abs(np.diff(times) - 0.1) > 0.0025
        if np.any(np.diff(times) <= 0):
            raise ValueError("nonmonotonic NFL frame timing")
        xx = play.x.to_numpy(dtype=float)
        # Preserve canonical 0..53.33 sideline distance under reflection.
        # Multiplying Y by -1 would make legitimate field coordinates invalid.
        raw_y = play.y.to_numpy(dtype=float)
        yy = raw_y if config.y_axis_sign == 1 else (160.0 / 3.0) - raw_y
        bad_jump = np.hypot(np.diff(xx), np.diff(yy)) > config.max_speed_yd_s * np.diff(times)
        breaks |= bad_jump
        rejected_gaps += int(breaks.sum())
        starts = np.r_[0, np.flatnonzero(breaks) + 1]
        ends = np.r_[starts[1:], len(play)]
        trial_id = ":".join(map(str, key))
        retained = 0
        for part, (start, end) in enumerate(zip(starts, ends, strict=True)):
            if end - start < config.min_frames_per_segment:
                continue
            segment = pd.DataFrame({
                "source_kind": "nfl", "source_id": "ROOKIE_REGULAR_SEASON",
                "segment_id": f"{trial_id}:part{part}",
                "independent_trial_id": trial_id,
                "player_id": str(key[3]),
                "frame_id": np.arange(end-start, dtype=int),
                "time_s": times[start:end] - times[start],
                "x": xx[start:end], "y": yy[start:end],
                "position": position, "draft_year": int(play.draft_year.iloc[0]),
            })
            out.append(segment)
            retained += end-start
        coverage.append({"independent_trial_id": trial_id, "player_id": str(key[3]),
                         "position": position, "draft_year": int(key[0]),
                         "frames_total": len(play), "frames_retained": retained,
                         "split_count": int(len(starts))})
    canonical = pd.concat(out, ignore_index=True) if out else pd.DataFrame()
    audit = {"position": position, "eligible_players": int(eligible.nfl_id.nunique()),
             "eligible_frames": int(len(eligible)), "retained_frames": int(len(canonical)),
             "unique_player_plays": len(coverage), "invalid_interval_boundaries": rejected_gaps,
             "excluded_non_routable_frames": int(len(tracking) - len(eligible)),
             "excluded_ball_or_missing_player_id": non_player_rows}
    return canonical, pd.DataFrame(coverage), audit


def rookie_linkage(combine_profiles: pd.DataFrame, nfl_profiles: pd.DataFrame) -> pd.DataFrame:
    """No correlation, rank or skills claim without independent adequate evidence.

    Keeps drill-specific rows, and exposes coverage when an NFL player is absent.
    """
    required = {"player_id", "position", "status", "asymmetry_pct", "source_id"}
    if not required.issubset(combine_profiles) or not required.issubset(nfl_profiles):
        raise ValueError("invalid movement profile tables")
    c = combine_profiles.loc[combine_profiles.source_kind.eq("combine")].copy()
    g = nfl_profiles.loc[nfl_profiles.source_kind.eq("nfl")].copy()
    if g.duplicated(["player_id", "position"]).any():
        raise ValueError("ambiguous NFL profile mapping for player")
    c = c.rename(columns={"status": "combine_status", "asymmetry_pct": "combine_asymmetry_pct",
                           "source_id": "combine_drill"})
    g = g[["player_id", "position", "status", "asymmetry_pct"]].rename(
        columns={"status": "nfl_status", "asymmetry_pct": "nfl_asymmetry_pct"})
    out = c.merge(g, on=["player_id", "position"], how="left", validate="many_to_one")
    out["nfl_status"] = out.nfl_status.fillna("no_rookie_tracking")
    out["link_status"] = np.where(
        out.combine_status.eq("estimated") & out.nfl_status.eq("estimated"),
        "paired_estimate_not_yet_validation", "insufficient_evidence")
    return out


def run_rookie_game_audit(source_dir: Path, output_dir: Path, *, position: str,
                          year: int, config: QualificationConfig,
                          rights_acknowledged: bool = False) -> dict:
    """Read only a requested single full season's official-format CSV in chunks.

    Only a selected position's prospect rows are accumulated; does not load all
    22M tracking frames or silently take a biased head() sample.
    """
    if year not in (2023, 2024, 2025) or position not in {"DB", "WR", "TE", "OL", "DL"}:
        raise ValueError("invalid season or position")
    if not rights_acknowledged:
        raise ValueError("competition source-use acknowledgement required")
    source_dir, output_dir = source_dir.resolve(), output_dir.resolve()
    if output_dir == source_dir or output_dir.is_relative_to(source_dir):
        raise ValueError("output must be outside licensed source directory")
    paths = {name: _local_file(source_dir / name) for name in
             ("players.csv", "games.csv", f"game_tracking_{year}.csv")}
    _header(paths["players.csv"], frozenset({"nfl_id", "combine_position", "draft_year"}))
    _header(paths["games.csv"], GAMES_KEYS)
    _header(paths[f"game_tracking_{year}.csv"], GAME_KEYS)
    p = pd.read_csv(paths["players.csv"])
    ids = set(_prepare_players(p).query("combine_position == @position").nfl_id)
    games = pd.read_csv(paths["games.csv"])
    chunks: list[pd.DataFrame] = []
    total = 0
    for frame in pd.read_csv(paths[f"game_tracking_{year}.csv"], chunksize=200_000, low_memory=False):
        total += len(frame)
        if not GAME_KEYS.issubset(frame.columns):
            raise ValueError("NFL tracking headers changed between chunks")
        selected = frame.loc[frame.nfl_id.astype("string").str.replace(r"\.0+$", "", regex=True).isin(ids)].copy()
        if not selected.empty:
            chunks.append(selected)
    if not chunks:
        raise ValueError("no selected player rows in NFL game file")
    canonical, coverage, audit = canonical_rookie_game(
        pd.concat(chunks, ignore_index=True), games, p, config, position=position)
    if canonical.empty:
        raise ValueError("no continuous NFL samples qualified")
    events = tag_event_field_sides(extract_turn_events(canonical), canonical)
    profiles = asymmetry_profiles(events)
    output_dir.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output_dir / f"nfl_{year}_{position}_play_coverage.csv", index=False)
    profiles.to_csv(output_dir / f"nfl_{year}_{position}_profiles_RESEARCH_ONLY.csv", index=False)
    audit["raw_game_rows_streamed"] = total
    audit["events"] = len(events)
    audit["profiles_estimated"] = int(profiles.status.eq("estimated").sum()) if len(profiles) else 0
    manifest = {
        "schema_version": 1, "authority": "RESEARCH_ONLY_NO_PROMOTION",
        "source_status": "USER_PROVIDED_NOT_INDEPENDENTLY_AUTHENTICATED",
        "handedness": "USER_DECLARED_NOT_VERIFIED",
        "source_files": {name: source_digest(path) for name, path in paths.items()},
        "audit": audit,
        "limitations": ["No head pose or anatomical strain inferred",
                        "Boundary/field side unavailable without verified ball and drive metadata",
                        "No NFL scouting effectiveness or prospective outcome validation",
                        "Do not commit player-level source derivatives to GitHub"],
    }
    (output_dir / f"nfl_{year}_{position}_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest
