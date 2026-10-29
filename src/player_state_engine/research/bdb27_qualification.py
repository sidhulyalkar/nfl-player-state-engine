"""BDB27 source-specific Combine qualification (research only, no network or promotion).

This adapter is *not* a claim that a third-party-described schema is the NFL's
canonical dictionary. Users must verify the source schema and handedness against
competition documentation before interpreting signed turns.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .bilateral import asymmetry_profiles, extract_turn_events

COMBINE_REQUIRED = frozenset({
    "nfl_id", "entity_type", "drill_name", "drill_type", "attempt",
    "event_id", "time", "x", "y",
})
PLAYERS_REQUIRED = frozenset({"nfl_id", "combine_position", "draft_year"})
GAME_REQUIRED = frozenset({"nfl_id", "game_id", "play_id", "x", "y", "time"})
SUPPORTED_GROUPS = frozenset({"DB", "WR", "TE", "OL", "DL"})
DRILL_ALIASES = {
    "LINE": "LINE_DRILL",
    "PASS_PRO-MIRROR_DRILL": "PASS_PRO_MIRROR_DRILL",
    "OVER_THE_SHOULDER_ADJUST": "OVER_SHOULDER_ADJUST",
    "SPEED_OUT_LEFT": "SPEED_OUT_ROUTE_LEFT",
}


@dataclass(frozen=True)
class QualificationConfig:
    # A caller declaration of raw coordinate handedness, NOT automatic verification.
    y_axis_sign: int
    min_frames_per_segment: int = 7
    nominal_hz: float = 10.0
    max_speed_yd_s: float = 14.0

    def __post_init__(self) -> None:
        if self.y_axis_sign not in (-1, 1):
            raise ValueError("y_axis_sign must be explicitly declared +1 or -1")
        if self.min_frames_per_segment < 5 or self.nominal_hz != 10.0:
            raise ValueError("unsupported sampling/segment contract")
        if not np.isfinite(self.max_speed_yd_s) or self.max_speed_yd_s <= 0:
            raise ValueError("invalid maximum plausible speed")


def source_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(2 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _local_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"missing, empty, or symlinked source file: {path.name}")
    return path


def _header(path: Path, required: frozenset[str]) -> list[str]:
    _local_file(path)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        header = next(csv.reader(stream), [])
    if not header or len(header) != len(set(header)) or not required.issubset(header):
        raise ValueError(f"invalid {path.name} header; missing {sorted(required - set(header))}")
    return header


def _prepare_players(players: pd.DataFrame) -> pd.DataFrame:
    if not PLAYERS_REQUIRED.issubset(players.columns):
        raise ValueError("players.csv lacks required player/position/year keys")
    out = players[["nfl_id", "combine_position", "draft_year"]].copy()
    if out.isna().any().any() or out.nfl_id.duplicated().any():
        raise ValueError("missing or duplicated players.csv player identifiers")
    out["nfl_id"] = out.nfl_id.astype("string").str.replace(r"\.0+$", "", regex=True)
    out["combine_position"] = out.combine_position.astype("string")
    if not set(out.combine_position).issubset(SUPPORTED_GROUPS):
        raise ValueError("unknown Combine position group")
    years = pd.to_numeric(out.draft_year, errors="coerce")
    if years.isna().any() or not years.isin([2023, 2024, 2025]).all():
        raise ValueError("unexpected draft cohort; confirm source identity")
    out["draft_year"] = years.astype(int)
    return out


def _prepare_raw(combine: pd.DataFrame, players: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    if not COMBINE_REQUIRED.issubset(combine.columns):
        raise ValueError("combine_tracking schema mismatch")
    raw = combine.copy()
    n_raw = len(raw)
    raw = raw.loc[raw.entity_type.eq("PLAYER")].copy()
    if raw.empty:
        raise ValueError("no PLAYER observations in Combine tracking")
    if raw[list(COMBINE_REQUIRED)].isna().any().any():
        raise ValueError("null critical tracking identity/time/position")
    raw["nfl_id"] = raw.nfl_id.astype("string").str.replace(r"\.0+$", "", regex=True)
    raw = raw.merge(players, on="nfl_id", how="left", validate="many_to_one", indicator=True)
    if (raw._merge != "both").any():
        raise ValueError("Combine frames have player IDs absent from players.csv")
    raw = raw.drop(columns="_merge")
    for name in ("x", "y"):
        raw[name] = pd.to_numeric(raw[name], errors="coerce")
        if not np.isfinite(raw[name].to_numpy(dtype=float)).all():
            raise ValueError(f"nonfinite source {name}")
    raw["time"] = pd.to_datetime(raw["time"], errors="coerce", utc=True, format="mixed")
    if raw.time.isna().any():
        raise ValueError("unparseable Combine timestamps")
    for name in ("drill_name", "drill_type", "attempt", "event_id"):
        raw[name] = raw[name].astype("string")
        if raw[name].str.strip().eq("").any():
            raise ValueError(f"blank {name}")
    raw["drill_name"] = raw.drill_name.replace(DRILL_ALIASES)
    return raw, {"raw_rows": n_raw, "player_rows": len(raw),
                 "filtered_non_player_rows": n_raw - len(raw),
                 "matched_players": int(raw.nfl_id.nunique()),
                 "positions": sorted(raw.combine_position.unique().tolist()),
                 "years": sorted(int(v) for v in raw.draft_year.unique())}


def canonical_combine(
    combine: pd.DataFrame, players: pd.DataFrame, config: QualificationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Convert complete official-format Combine inputs to continuous trial segments.

    Every contiguous subsegment of one attempt shares independent_trial_id.
    No missing frames are fabricated. Bad/sparse segments are audited, not used.
    The source data's x/y units and sign must be externally checked first.
    """
    p = _prepare_players(players)
    raw, audit = _prepare_raw(combine, p)
    keys = ["draft_year", "nfl_id", "drill_type", "drill_name", "attempt", "event_id"]
    if raw.duplicated(keys + ["time"]).any():
        raise ValueError("duplicate timestamps within one drill event/attempt")
    raw = raw.sort_values(keys + ["time"], kind="mergesort")
    step = 1.0 / config.nominal_hz
    segments: list[pd.DataFrame] = []
    trial_rows: list[dict] = []
    bad_intervals = 0
    discarded = 0
    bad_speed = 0
    for key, trial in raw.groupby(keys, sort=False, dropna=False):
        trial = trial.reset_index(drop=True)
        t = (trial.time - trial.time.iloc[0]).dt.total_seconds().to_numpy(dtype=float)
        x = trial.x.to_numpy(dtype=float)
        y = config.y_axis_sign * trial.y.to_numpy(dtype=float)
        interval = np.diff(t)
        displacement = np.hypot(np.diff(x), np.diff(y))
        # Reject suspicious teleports; never use spurious derivative peaks.
        breaks = (np.abs(interval - step) > 0.0025) | (interval <= 0)
        breaks |= displacement > config.max_speed_yd_s * np.maximum(interval, 0)
        bad_intervals += int(breaks.sum())
        bad_speed += int((displacement > config.max_speed_yd_s * np.maximum(interval, 0)).sum())
        starts = np.r_[0, np.flatnonzero(breaks) + 1]
        ends = np.r_[starts[1:], len(trial)]
        trial_id = ":".join(str(v) for v in key)
        retained = 0
        for part, (start, end) in enumerate(zip(starts, ends, strict=True)):
            if end - start < config.min_frames_per_segment:
                discarded += end - start
                continue
            one = trial.iloc[start:end]
            seg = pd.DataFrame({
                "source_kind": "combine", "source_id": str(key[3]),
                "segment_id": f"{trial_id}:part{part}",
                "independent_trial_id": trial_id, "player_id": str(key[1]),
                "frame_id": np.arange(len(one), dtype=int),
                "time_s": t[start:end] - t[start],
                "x": x[start:end], "y": y[start:end],
                "position": str(one.combine_position.iloc[0]),
                "draft_year": int(key[0]), "drill_type": str(key[2]),
            })
            segments.append(seg)
            retained += len(one)
        trial_rows.append({"independent_trial_id": trial_id, "player_id": str(key[1]),
                           "position": str(trial.combine_position.iloc[0]),
                           "draft_year": int(key[0]), "drill_name": str(key[3]),
                           "frames_total": len(trial), "frames_retained": retained,
                           "continuous_parts": int(sum((ends - starts) >= config.min_frames_per_segment)),
                           "sample_gaps": int(breaks.sum())})
    columns = ["source_kind", "source_id", "segment_id", "independent_trial_id",
               "player_id", "frame_id", "time_s", "x", "y", "position", "draft_year", "drill_type"]
    canonical = pd.concat(segments, ignore_index=True) if segments else pd.DataFrame(columns=columns)
    trials = pd.DataFrame(trial_rows)
    audit.update({"unique_trials": len(trials), "retained_frames": len(canonical),
                  "discarded_short_segment_frames": int(discarded),
                  "rejected_intervals": bad_intervals, "rejected_teleports": bad_speed,
                  "trial_coverage_pct": round(100 * float(trials.frames_retained.gt(0).mean()), 3),
                  "retained_frame_pct": round(100 * len(canonical) / len(raw), 3)})
    return canonical, trials, audit


def eligibility_by_drill(events: pd.DataFrame, trials: pd.DataFrame) -> pd.DataFrame:
    """Report event replication and within-bin overlap, NOT player rankings."""
    out: list[dict] = []
    if trials.empty:
        return pd.DataFrame()
    e = events.copy()
    trial_meta = trials[["independent_trial_id", "draft_year", "drill_name"]]
    if not e.empty:
        e = e.merge(trial_meta, on="independent_trial_id", how="left", validate="many_to_one")
    for (position, drill), group in trials.groupby(["position", "drill_name"], sort=True):
        sub = e.loc[(e.position == position) & (e.drill_name == drill)] if len(e) else e
        # Eligibility is a deterministic coverage gate. Do not run hundreds
        # of bootstrap fits just to count athletes with adequate replication.
        qualifying = 0
        if len(sub):
            for _, athlete in sub.groupby("player_id", sort=False):
                left = athlete.loc[athlete.turn.eq("left")]
                right = athlete.loc[athlete.turn.eq("right")]
                shared_bins = (set(zip(left.speed_bin, left.angle_bin, strict=True)) &
                               set(zip(right.speed_bin, right.angle_bin, strict=True)))
                if not shared_bins:
                    continue
                shared = athlete.loc[[
                    (speed, angle) in shared_bins
                    for speed, angle in zip(athlete.speed_bin, athlete.angle_bin, strict=True)
                ]]
                nl = shared.loc[shared.turn.eq("left"), "independent_trial_id"].nunique()
                nr = shared.loc[shared.turn.eq("right"), "independent_trial_id"].nunique()
                if nl >= 3 and nr >= 3:
                    qualifying += 1
        out.append({"position": position, "drill_name": drill,
                    "players_with_trials": int(group.player_id.nunique()),
                    "total_independent_trials": len(group),
                    "turn_events": len(sub),
                    "players_with_estimable_bilateral_asymmetry": qualifying,
                    "cohorts_present": ",".join(map(str, sorted(group.draft_year.unique())))})
    return pd.DataFrame(out)


def qualify_directory(source_dir: Path, output_dir: Path, config: QualificationConfig,
                      *, source_rights_acknowledged: bool = False) -> dict:
    """Read only official-format local CSVs and write local-only audit outputs.

    No network; does not authenticate the rights assertion or raw coordinate map.
    Data remain at the user's discretion: generated player tables are not for Git.
    """
    source_dir, output_dir = source_dir.resolve(), output_dir.resolve()
    if source_dir == output_dir or output_dir.is_relative_to(source_dir):
        raise ValueError("output must be outside licensed source directory")
    if not source_rights_acknowledged:
        raise ValueError("explicit acknowledgement of applicable competition data terms required")
    combine_path = _local_file(source_dir / "combine_tracking.csv")
    players_path = _local_file(source_dir / "players.csv")
    combine_header = _header(combine_path, COMBINE_REQUIRED)
    players_header = _header(players_path, PLAYERS_REQUIRED)
    # Full Combine fits in ordinary memory. Stream game tracking in a later
    # outcome-validation stage, never silently load 22M frames here.
    combine = pd.read_csv(combine_path, low_memory=False)
    players = pd.read_csv(players_path, low_memory=False)
    canonical, trials, audit = canonical_combine(combine, players, config)
    if canonical.empty:
        raise ValueError("no continuous source segments passed qualification")
    events = extract_turn_events(canonical)
    coverage = eligibility_by_drill(events, trials)
    profiles = asymmetry_profiles(events)
    output_dir.mkdir(parents=True, exist_ok=True)
    trials.to_csv(output_dir / "attempt_coverage.csv", index=False)
    coverage.to_csv(output_dir / "eligibility_by_drill.csv", index=False)
    events.to_csv(output_dir / "turn_events_RESEARCH_ONLY.csv", index=False)
    profiles.to_csv(output_dir / "asymmetry_RESEARCH_ONLY.csv", index=False)
    audit.update({"n_events": len(events), "profiles": len(profiles),
                  "estimated_profiles": int(profiles.status.eq("estimated").sum()) if len(profiles) else 0})
    manifest = {
        "schema_version": 1, "authority": "RESEARCH_ONLY_NO_PROMOTION",
        "source_status": "USER_PROVIDED_CSVS_NOT_INDEPENDENTLY_AUTHENTICATED",
        "coordinate_handedness": "USER_DECLARED_NOT_VERIFIED",
        "y_axis_sign": config.y_axis_sign,
        "license_acknowledged_by_user": True,
        "sources": {path.name: {"sha256": source_digest(path),
                                "bytes": path.stat().st_size,
                                "columns": header} for path, header in [
                                    (combine_path, combine_header), (players_path, players_header)]},
        "audit": audit,
        "limitations": [
            "Combine coordinate handedness must be checked against primary source documentation",
            "Only observed path turns, not anatomical plant leg, visual attention or strain",
            "A split trajectory is not an independent drill attempt",
            "Official rookie NFL tracking and position-outcome validation not yet performed",
            "No video or eye-gaze ground truth supplied",
            "No competition player-level data should be committed to this repository",
        ],
    }
    (output_dir / "qualification_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
