from __future__ import annotations

import numpy as np
import pandas as pd


def _numeric(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def _coalesce(frame: pd.DataFrame, names: tuple[str, ...], default: object = np.nan) -> pd.Series:
    out = pd.Series(default, index=frame.index)
    for name in names:
        if name in frame:
            values = frame[name]
            out = out.where(out.notna(), values)
    return out


def _normalize_game_id(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "game_id" not in out and "nflverse_game_id" in out:
        out["game_id"] = out["nflverse_game_id"]
    if "game_id" not in out:
        raise ValueError("Play intelligence requires game_id or nflverse_game_id")
    return out


def _merge_optional(
    base: pd.DataFrame,
    optional: pd.DataFrame | None,
    *,
    suffix: str,
) -> pd.DataFrame:
    if optional is None or optional.empty:
        return base
    right = _normalize_game_id(optional)
    keys = [column for column in ("game_id", "play_id") if column in base and column in right]
    if len(keys) < 2:
        return base
    keep = keys + [column for column in right if column not in keys and column not in base]
    renamed = right.loc[:, keep].copy()
    duplicate_columns = [column for column in renamed if column in base and column not in keys]
    renamed = renamed.rename(columns={column: f"{column}_{suffix}" for column in duplicate_columns})
    return base.merge(renamed, on=keys, how="left", validate="many_to_one")


def build_play_intelligence_frame(
    pbp: pd.DataFrame,
    participation: pd.DataFrame | None = None,
    charting: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Normalize play-level football evidence without introducing future information.

    Every row represents an observed historical play. Pregame models must derive lagged or
    expanding features from this frame; same-game outcomes in this table are labels, not
    prediction-time inputs.
    """
    data = _normalize_game_id(pbp)
    required = {"season", "week", "play_id", "posteam", "defteam"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Play intelligence missing columns: {sorted(missing)}")
    data = _merge_optional(data, participation, suffix="participation")
    data = _merge_optional(data, charting, suffix="charting")
    data = data.loc[data["posteam"].notna() & data["defteam"].notna()].copy()
    data = data.sort_values(["season", "week", "game_id", "play_id"], kind="mergesort")

    pass_attempt = _numeric(data, "pass_attempt")
    rush_attempt = _numeric(data, "rush_attempt")
    qb_dropback = _numeric(data, "qb_dropback")
    sack = _numeric(data, "sack")
    scramble = _numeric(data, "qb_scramble")
    data["is_dropback"] = ((pass_attempt + qb_dropback + sack + scramble) > 0).astype(int)
    data["is_rush"] = ((rush_attempt > 0) & data["is_dropback"].eq(0)).astype(int)
    data["is_scrimmage_play"] = (data["is_dropback"] + data["is_rush"]).gt(0).astype(int)
    data = data.loc[data["is_scrimmage_play"].eq(1)].copy()
    data["play_family"] = np.where(data["is_dropback"].eq(1), "DROPBACK", "RUSH")

    data["down"] = _numeric(data, "down", 1).clip(1, 4).astype(int)
    data["ydstogo"] = _numeric(data, "ydstogo", 10).clip(0, 40)
    data["yardline_100"] = _numeric(data, "yardline_100", 75).clip(0, 100)
    data["qtr"] = _numeric(data, "qtr", 1).clip(1, 5).astype(int)
    if "game_seconds_remaining" in data:
        remaining = _numeric(data, "game_seconds_remaining", 3600)
    else:
        quarter_seconds = _numeric(data, "quarter_seconds_remaining", 900)
        remaining = ((4 - data["qtr"].clip(upper=4)) * 900 + quarter_seconds).clip(0, 3600)
    data["game_seconds_remaining"] = remaining
    data["score_differential"] = _numeric(data, "score_differential", 0)
    data["neutral_score_state"] = data["score_differential"].abs().le(7).astype(int)
    data["late_game"] = data["game_seconds_remaining"].le(900).astype(int)
    data["red_zone"] = data["yardline_100"].le(20).astype(int)
    data["goal_to_go_state"] = _numeric(data, "goal_to_go", 0).clip(0, 1)
    data["distance_bucket"] = pd.cut(
        data["ydstogo"], [-0.1, 2, 6, 10, np.inf], labels=[0, 1, 2, 3]
    ).astype(int)
    data["field_zone"] = pd.cut(
        data["yardline_100"], [-0.1, 20, 40, 60, 80, 100.1], labels=[0, 1, 2, 3, 4]
    ).astype(int)

    data["shotgun_flag"] = _numeric(data, "shotgun").clip(0, 1)
    data["no_huddle_flag"] = _numeric(data, "no_huddle").clip(0, 1)
    data["motion_flag"] = _numeric(
        data,
        "is_motion" if "is_motion" in data else "motion" if "motion" in data else "shift",
    ).clip(0, 1)
    data["play_action_flag"] = _numeric(data, "is_play_action").clip(0, 1)
    data["rpo_flag"] = _numeric(data, "is_rpo").clip(0, 1)
    data["screen_flag"] = _numeric(data, "is_screen_pass").clip(0, 1)
    data["defenders_in_box"] = pd.to_numeric(
        _coalesce(data, ("defenders_in_box", "defenders_in_box_participation")),
        errors="coerce",
    )
    data["number_of_pass_rushers"] = pd.to_numeric(
        _coalesce(data, ("number_of_pass_rushers", "n_pass_rushers")),
        errors="coerce",
    )
    data["offense_formation"] = _coalesce(data, ("offense_formation",)).astype("string")
    data["offense_personnel"] = _coalesce(data, ("offense_personnel",)).astype("string")
    data["defense_personnel"] = _coalesce(data, ("defense_personnel",)).astype("string")

    data["yards_gained"] = _numeric(data, "yards_gained")
    data["touchdown"] = _numeric(data, "touchdown").clip(0, 1).astype(int)
    data["first_down"] = _numeric(data, "first_down").clip(0, 1).astype(int)
    data["complete_pass"] = _numeric(data, "complete_pass").clip(0, 1).astype(int)
    data["interception"] = _numeric(data, "interception").clip(0, 1).astype(int)
    data["fumble_lost"] = _numeric(data, "fumble_lost").clip(0, 1).astype(int)
    data["turnover"] = ((data["interception"] + data["fumble_lost"]) > 0).astype(int)
    data["epa"] = _numeric(data, "epa")
    data["explosive_play"] = (
        ((data["play_family"].eq("RUSH")) & data["yards_gained"].ge(10))
        | ((data["play_family"].eq("DROPBACK")) & data["yards_gained"].ge(20))
    ).astype(int)

    drive = data["drive"] if "drive" in data else pd.Series(0, index=data.index)
    groups = [data["game_id"], drive, data["posteam"]]
    grouped_clock = data.groupby(groups, sort=False)["game_seconds_remaining"]
    previous_clock = grouped_clock.shift(1)
    next_clock = grouped_clock.shift(-1)
    data["seconds_between_plays"] = (previous_clock - data["game_seconds_remaining"]).clip(0, 90)
    data["seconds_to_next_play"] = (data["game_seconds_remaining"] - next_clock).clip(0, 90)

    data["passer_player_id"] = _coalesce(
        data, ("passer_player_id", "passer_id", "passer_player_id_charting")
    )
    data["receiver_player_id"] = _coalesce(
        data, ("receiver_player_id", "receiver_id", "receiver_player_id_charting")
    )
    data["rusher_player_id"] = _coalesce(
        data, ("rusher_player_id", "rusher_id", "rusher_player_id_charting")
    )

    data["has_live_pbp_context"] = True
    data["has_participation_context"] = data["offense_formation"].notna()
    data["has_charting_context"] = (
        data[["motion_flag", "play_action_flag", "rpo_flag", "screen_flag"]].abs().sum(axis=1).gt(0)
    )
    return data.reset_index(drop=True)
