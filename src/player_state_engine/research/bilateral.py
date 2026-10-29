"""Research-only directional movement, independent of the fantasy forecasting pipeline.

All x/y inputs MUST be right-handed fixed-field coordinates in yards:
+X is stadium east, +Y is stadium north; cross(+X,+Y) points up.
A LEFT turn means counter-clockwise turning of the velocity vector, not a
left-foot plant, anatomical weakness, head direction, or tactical judgment.

No inference of NFL raw coordinate conventions, team directions, gaze, joint
forces or injury risk is made. External source mapping is explicit and upstream.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

FRAME_COLUMNS = ("source_kind", "source_id", "segment_id", "player_id", "frame_id", "time_s", "x", "y")
EVENT_COLUMNS = (
    "source_kind", "source_id", "segment_id", "player_id", "frame_id", "time_s",
    "turn", "turn_angle_deg", "entry_speed_yd_s", "exit_speed_yd_s",
    "speed_retention", "speed_bin", "angle_bin", "position",
)


@dataclass(frozen=True)
class FieldFrame:
    """Canonical fixed-field geometry, not an inference about raw NFL schemas."""

    field_width_yards: float = 160.0 / 3.0
    midfield_tolerance_yards: float = 2.0

    def __post_init__(self) -> None:
        if not np.isfinite(self.field_width_yards) or self.field_width_yards <= 0:
            raise ValueError("field_width_yards must be positive and finite")
        if not (0 <= self.midfield_tolerance_yards < self.field_width_yards / 2):
            raise ValueError("invalid midfield_tolerance_yards")


def field_context(
    x: float,
    y: float,
    *,
    offense_direction: int | None,
    ball_y: float | None = None,
    geometry: FieldFrame = FieldFrame(),
) -> dict[str, float | str | None]:
    """Report different field-side notions without conflating body and stadium sides.

    offense_direction=+1 means toward +X; -1 means toward -X. `ball_y` is
    required for the short-side / wide-side distinction. In the middle of the
    field there is no defensible boundary/field classification, so abstain.
    """
    w = geometry.field_width_yards
    if not all(np.isfinite(v) for v in (x, y)) or not 0 <= y <= w:
        raise ValueError("x/y must be finite and y within canonical field width")
    if offense_direction not in (+1, -1, None):
        raise ValueError("offense_direction must be +1, -1, or None")
    center = w / 2
    dist = min(y, w - y)
    offense_side = None
    if offense_direction is not None and abs(y - center) > geometry.midfield_tolerance_yards:
        offense_side = "left" if offense_direction * (y - center) > 0 else "right"
    tactical_side = None
    if ball_y is not None:
        if not np.isfinite(ball_y) or not 0 <= ball_y <= w:
            raise ValueError("ball_y must be within canonical field width")
        if abs(ball_y - center) > geometry.midfield_tolerance_yards and abs(y - center) > geometry.midfield_tolerance_yards:
            tactical_side = "boundary" if (ball_y - center) * (y - center) > 0 else "field"
    return {
        "stadium_y": float(y),
        "distance_to_nearest_sideline_yd": float(dist),
        "offense_left_right": offense_side,
        "boundary_field": tactical_side,
        "offense_downfield_x": float(offense_direction * x) if offense_direction else None,
    }


def _validate_frames(tracking: pd.DataFrame, hz: float) -> pd.DataFrame:
    if not np.isfinite(hz) or hz <= 0:
        raise ValueError("hz must be positive")
    missing = set(FRAME_COLUMNS).difference(tracking.columns)
    if missing:
        raise ValueError(f"missing canonical columns: {sorted(missing)}")
    if tracking.empty:
        raise ValueError("tracking input is empty")
    df = tracking.copy()
    for col in ("x", "y", "time_s", "frame_id"):
        vals = pd.to_numeric(df[col], errors="coerce")
        if not np.isfinite(vals.to_numpy(dtype=float)).all():
            raise ValueError(f"invalid/nonfinite {col}")
        df[col] = vals
    for col in ("source_kind", "source_id", "segment_id", "player_id"):
        if df[col].isna().any() or (df[col].astype(str).str.len() == 0).any():
            raise ValueError(f"missing/invalid identity {col}")
    if not set(df.source_kind).issubset({"combine", "nfl"}):
        raise ValueError("source_kind must be 'combine' or 'nfl'")
    group = ["source_kind", "source_id", "segment_id", "player_id"]
    if df.duplicated(subset=group + ["frame_id"]).any():
        raise ValueError("duplicate frame within a player/source/segment")
    df = df.sort_values(group + ["time_s", "frame_id"], kind="mergesort")
    for _, seg in df.groupby(group, sort=False):
        dt = np.diff(seg.time_s.to_numpy(dtype=float))
        # A missing frame invalidates derivatives for the *whole* input segment;
        # explicitly split input into contiguous segments upstream instead.
        if dt.size and (np.any(dt <= 0) or np.any(np.abs(dt - 1.0 / hz) > 0.025 / hz)):
            raise ValueError("nonmonotonic or noncontiguous sampling; split segments upstream")
        frame_delta = np.diff(seg.frame_id.to_numpy(dtype=float))
        if frame_delta.size and not np.all(frame_delta == 1):
            raise ValueError("frame index gaps; split segments upstream")
        if "position" in seg.columns and (seg.position.isna().any() or seg.position.nunique(dropna=False) != 1):
            raise ValueError("missing or changing position within segment")
    return df


def _speed_bin(value: float) -> str:
    # 2 yd/s bins, explicitly prespecified to avoid post hoc matching.
    low = 2 * int(value // 2)
    return f"[{low},{low + 2})"


def _angle_bin(value: float) -> str:
    for upper, label in ((75, "[45,75)"), (110, "[75,110)"), (181, "[110,180]")):
        if value < upper:
            return label
    raise ValueError("turn angle outside allowable range")


def extract_turn_events(
    tracking: pd.DataFrame,
    *,
    hz: float = 10.0,
    window_frames: int = 2,
    minimum_turn_deg: float = 45.0,
    minimum_speed_yd_s: float = 1.5,
    minimum_separation_s: float = 0.6,
) -> pd.DataFrame:
    """Extract separated signed path turns from contiguous player trajectories.

    Averages displacement across pre/post windows; does not use single-frame
    acceleration peaks. Samples < (2*window+1) or events with inadequate speed
    are excluded. Output is a research event table, never a cognitive score.
    """
    if window_frames < 2 or not 45 <= minimum_turn_deg < 180 or minimum_speed_yd_s <= 0:
        raise ValueError("invalid extractor settings")
    if minimum_separation_s < (2 * window_frames) / hz:
        raise ValueError("minimum_separation_s must span the full event window")
    df = _validate_frames(tracking, hz)
    rows: list[dict] = []
    keys = ["source_kind", "source_id", "segment_id", "player_id"]
    k = window_frames
    for group, seg in df.groupby(keys, sort=False):
        if len(seg) < 2 * k + 1:
            continue
        xyz = seg[["x", "y"]].to_numpy(dtype=float)
        times = seg.time_s.to_numpy(dtype=float)
        candidates: list[tuple[float, int, float, float, float]] = []
        for t in range(k, len(seg) - k):
            vi = (xyz[t] - xyz[t - k]) / (times[t] - times[t - k])
            vo = (xyz[t + k] - xyz[t]) / (times[t + k] - times[t])
            s0, s1 = float(np.linalg.norm(vi)), float(np.linalg.norm(vo))
            if min(s0, s1) < minimum_speed_yd_s:
                continue
            cross = vi[0] * vo[1] - vi[1] * vo[0]
            angle = float(np.degrees(np.arctan2(cross, np.dot(vi, vo))))
            if minimum_turn_deg <= abs(angle) < 179.0:
                candidates.append((abs(angle), t, angle, s0, s1))
        # Nonmaximum suppression: prefer the largest turn in a time neighborhood.
        chosen: list[tuple[float, int, float, float, float]] = []
        for candidate in sorted(candidates, key=lambda item: (-item[0], item[1])):
            if all(abs(times[candidate[1]] - times[p[1]]) >= minimum_separation_s for p in chosen):
                chosen.append(candidate)
        for _, t, angle, s0, s1 in sorted(chosen, key=lambda item: item[1]):
            meta = dict(zip(keys, group, strict=True))
            meta.update({
                "frame_id": int(seg.iloc[t].frame_id),
                "time_s": float(times[t]),
                "turn": "left" if angle > 0 else "right",
                "turn_angle_deg": abs(angle),
                "entry_speed_yd_s": s0,
                "exit_speed_yd_s": s1,
                "speed_retention": s1 / s0,
                "speed_bin": _speed_bin(s0),
                "angle_bin": _angle_bin(abs(angle)),
                "position": str(seg.iloc[t]["position"]) if "position" in seg else "unassigned",
            })
            rows.append(meta)
    return pd.DataFrame(rows, columns=EVENT_COLUMNS)


def _matched_delta(subset: pd.DataFrame) -> float | None:
    differences: list[float] = []
    weights: list[int] = []
    for _, chunk in subset.groupby(["speed_bin", "angle_bin"], sort=False):
        left = chunk.loc[chunk.turn == "left", "speed_retention"].to_numpy(dtype=float)
        right = chunk.loc[chunk.turn == "right", "speed_retention"].to_numpy(dtype=float)
        if len(left) == 0 or len(right) == 0:
            continue
        denom = (left.mean() + right.mean()) / 2
        if denom <= 0:
            continue
        differences.append(float(100 * (right.mean() - left.mean()) / denom))
        weights.append(min(len(left), len(right)))
    return float(np.average(differences, weights=weights)) if weights else None


def asymmetry_profiles(
    events: pd.DataFrame,
    *,
    minimum_independent_segments: int = 3,
    bootstrap_samples: int = 400,
    seed: int = 2027,
) -> pd.DataFrame:
    """Compare right-versus-left *path turn* retention in matched demand bins.

    Resamples whole segments, not 10 Hz tracking rows. Abstains when either
    direction lacks independent segments or bins do not overlap. Results do NOT
    imply joint strain, injury risk, perception or true physical dominance.
    """
    required = set(EVENT_COLUMNS)
    if not required.issubset(events.columns):
        raise ValueError(f"missing event fields: {sorted(required - set(events.columns))}")
    if minimum_independent_segments < 2 or bootstrap_samples < 100:
        raise ValueError("insufficient uncertainty evaluation settings")
    if events.empty:
        return pd.DataFrame(columns=["source_kind", "source_id", "player_id", "position", "status", "asymmetry_pct", "ci_low_pct", "ci_high_pct", "n_left", "n_right", "segments_left", "segments_right", "matched_bins"])
    vals = pd.to_numeric(events.speed_retention, errors="coerce")
    if not np.isfinite(vals.to_numpy(dtype=float)).all() or (vals <= 0).any():
        raise ValueError("invalid retention metric")
    if not events.turn.isin(["left", "right"]).all():
        raise ValueError("event turn must be left or right")
    result: list[dict] = []
    groups = ["source_kind", "source_id", "player_id", "position"]
    for key, chunk in events.groupby(groups, sort=True):
        left = chunk.loc[chunk.turn == "left"]
        right = chunk.loc[chunk.turn == "right"]
        bins_left = set(zip(left.speed_bin, left.angle_bin, strict=True))
        bins_right = set(zip(right.speed_bin, right.angle_bin, strict=True))
        intersection = bins_left & bins_right
        subset = chunk.loc[[
            (speed, angle) in intersection
            for speed, angle in zip(chunk.speed_bin, chunk.angle_bin, strict=True)
        ]].copy()
        estimate = _matched_delta(subset)
        nleft = subset.loc[subset.turn == "left", "segment_id"].nunique()
        nright = subset.loc[subset.turn == "right", "segment_id"].nunique()
        record = dict(zip(groups, key, strict=True))
        record.update({"status": "insufficient_matched_evidence", "asymmetry_pct": None,
                       "ci_low_pct": None, "ci_high_pct": None,
                       "n_left": int((subset.turn == "left").sum()),
                       "n_right": int((subset.turn == "right").sum()),
                       "segments_left": nleft, "segments_right": nright,
                       "matched_bins": len(intersection)})
        if nleft >= minimum_independent_segments and nright >= minimum_independent_segments and estimate is not None:
            # Global block bootstrap preserves within-segment left/right dependence.
            rng = np.random.default_rng(seed)
            segments = subset.segment_id.drop_duplicates().to_list()
            boot: list[float] = []
            blocks = {s: subset.loc[subset.segment_id == s] for s in segments}
            for _ in range(bootstrap_samples):
                draw = rng.choice(len(segments), size=len(segments), replace=True)
                resampled = pd.concat([blocks[segments[j]] for j in draw], ignore_index=True)
                d = _matched_delta(resampled)
                if (d is not None
                        and resampled.loc[resampled.turn == "left", "segment_id"].nunique() >= 2
                        and resampled.loc[resampled.turn == "right", "segment_id"].nunique() >= 2):
                    boot.append(d)
            if len(boot) >= bootstrap_samples * 0.8:
                lo, hi = np.quantile(boot, [0.025, 0.975])
                record.update({"status": "estimated", "asymmetry_pct": estimate,
                               "ci_low_pct": float(lo), "ci_high_pct": float(hi)})
        result.append(record)
    return pd.DataFrame(result)
