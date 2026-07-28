from __future__ import annotations

import numpy as np
import pandas as pd


def _binary(frame: pd.DataFrame, column: str, values: set[str]) -> pd.Series:
    if column not in frame:
        return pd.Series(False, index=frame.index)
    return frame[column].astype(str).str.lower().isin(values)


def build_team_play_structure(pbp: pd.DataFrame) -> pd.DataFrame:
    """Create pregame-ready team/coaching fingerprints from play-by-play.

    Outputs describe observable play calling, pace, formation and opportunity
    concentration. They are not proprietary playbooks or claims about intent.
    """
    required = {"season", "week", "posteam"}
    missing = required - set(pbp)
    if missing:
        raise ValueError(f"Play structure requires columns: {sorted(missing)}")
    data = pbp.copy()
    data = data.loc[data["posteam"].notna()].copy()

    def series(name: str, default: float = 0.0) -> pd.Series:
        return pd.to_numeric(
            data[name] if name in data else pd.Series(default, index=data.index), errors="coerce"
        ).fillna(default)

    data["is_pass"] = series("pass_attempt").clip(0, 1)
    data["is_rush"] = series("rush_attempt").clip(0, 1)
    data["is_play"] = ((data["is_pass"] + data["is_rush"]) > 0).astype(int)
    data["neutral"] = series("score_differential").abs().le(7) & series("qtr", 1).le(3)
    data["red_zone"] = series("yardline_100", 100).le(20)
    data["shotgun_flag"] = series("shotgun")
    data["no_huddle_flag"] = series("no_huddle")
    data["motion_flag"] = series("motion") if "motion" in data else series("shift")
    data["seconds_between_plays"] = pd.to_numeric(
        data["play_clock"] if "play_clock" in data else pd.Series(np.nan, index=data.index),
        errors="coerce",
    )

    keys = ["season", "week", "posteam"]
    rows = []
    for key, group in data.groupby(keys, dropna=False):
        plays = group.loc[group["is_play"].eq(1)]
        if plays.empty:
            continue
        neutral = plays.loc[plays["neutral"]]
        rz = plays.loc[plays["red_zone"]]
        target_counts = (
            group.get("receiver_player_id", pd.Series(index=group.index, dtype=object))
            .dropna()
            .value_counts()
        )
        carry_counts = (
            group.get("rusher_player_id", pd.Series(index=group.index, dtype=object))
            .dropna()
            .value_counts()
        )

        def hhi(counts: pd.Series) -> float:
            if counts.empty or counts.sum() == 0:
                return np.nan
            share = counts / counts.sum()
            return float((share**2).sum())

        rows.append(
            {
                "season": key[0],
                "week": key[1],
                "recent_team": key[2],
                "team_plays_actual": float(len(plays)),
                "team_pass_rate_actual": float(plays["is_pass"].mean()),
                "team_neutral_pass_rate_actual": float(neutral["is_pass"].mean())
                if len(neutral)
                else np.nan,
                "team_red_zone_pass_rate_actual": float(rz["is_pass"].mean())
                if len(rz)
                else np.nan,
                "team_shotgun_rate_actual": float(plays["shotgun_flag"].mean()),
                "team_no_huddle_rate_actual": float(plays["no_huddle_flag"].mean()),
                "team_motion_rate_actual": float(plays["motion_flag"].mean()),
                "team_target_hhi_actual": hhi(target_counts),
                "team_carry_hhi_actual": hhi(carry_counts),
                "team_seconds_between_plays_actual": float(plays["seconds_between_plays"].median())
                if plays["seconds_between_plays"].notna().any()
                else np.nan,
            }
        )
    weekly = pd.DataFrame(rows).sort_values(["recent_team", "season", "week"])
    actual_cols = [c for c in weekly if c.endswith("_actual")]
    for column in actual_cols:
        shifted = weekly.groupby("recent_team", sort=False)[column].shift(1)
        weekly[column.replace("_actual", "_lag1")] = shifted
        weekly[column.replace("_actual", "_roll4")] = (
            shifted.groupby(weekly["recent_team"], sort=False)
            .rolling(4, min_periods=1)
            .mean()
            .reset_index(level=0, drop=True)
        )
    return weekly


def add_coaching_continuity(team_context: pd.DataFrame, coaches: pd.DataFrame) -> pd.DataFrame:
    required = {"season", "recent_team", "head_coach", "offensive_coordinator"}
    missing = required - set(coaches)
    if missing:
        raise ValueError(f"Coaching table missing: {sorted(missing)}")
    coach = coaches.copy().sort_values(["recent_team", "season"])
    coach["head_coach_changed"] = (
        coach.groupby("recent_team")["head_coach"].shift(1).ne(coach["head_coach"]).astype(int)
    )
    coach["offensive_coordinator_changed"] = (
        coach.groupby("recent_team")["offensive_coordinator"]
        .shift(1)
        .ne(coach["offensive_coordinator"])
        .astype(int)
    )
    return team_context.merge(
        coach, on=["season", "recent_team"], how="left", validate="many_to_one"
    )


def _pct_by_season(frame: pd.DataFrame, column: str, *, ascending: bool = True) -> pd.Series:
    values = (
        pd.to_numeric(frame[column], errors="coerce")
        if column in frame
        else pd.Series(np.nan, index=frame.index)
    )
    ranked = values.groupby(frame["season"], sort=False).rank(pct=True, ascending=ascending)
    return ranked.fillna(0.5)


def score_player_scheme_fit(players: pd.DataFrame, team_context: pd.DataFrame) -> pd.DataFrame:
    """Estimate observable player-to-system fit from historical play structure.

    This is intentionally a role-context score, not an attempt to reconstruct a
    private playbook. Only lagged/rolling team tendencies are accepted.
    """
    required_players = {"season", "recent_team", "position"}
    missing = required_players - set(players)
    if missing:
        raise ValueError(f"Player scheme fit missing: {sorted(missing)}")
    context = team_context.copy()
    forbidden = [c for c in context if c.endswith("_actual")]
    context = context.drop(columns=forbidden, errors="ignore")
    keys = ["season", "recent_team"]
    if "week" in players and "week" in context:
        keys.append("week")
    data = players.merge(context, on=keys, how="left", suffixes=("", "_team"))

    pass_rate = _pct_by_season(data, "team_neutral_pass_rate_roll4")
    pace = 1.0 - _pct_by_season(data, "team_seconds_between_plays_roll4")
    shotgun = _pct_by_season(data, "team_shotgun_rate_roll4")
    motion = _pct_by_season(data, "team_motion_rate_roll4")
    target_concentration = _pct_by_season(data, "team_target_hhi_roll4")
    carry_concentration = _pct_by_season(data, "team_carry_hhi_roll4")
    red_zone_pass = _pct_by_season(data, "team_red_zone_pass_rate_roll4")

    position = data["position"].astype(str).str.upper()
    score = pd.Series(0.5, index=data.index, dtype=float)
    qb = position.eq("QB")
    rb = position.eq("RB")
    receiver = position.isin(["WR", "TE"])
    score.loc[qb] = (
        0.35 * pass_rate.loc[qb]
        + 0.20 * pace.loc[qb]
        + 0.25 * shotgun.loc[qb]
        + 0.10 * motion.loc[qb]
        + 0.10 * red_zone_pass.loc[qb]
    )
    score.loc[rb] = (
        0.30 * (1.0 - pass_rate.loc[rb])
        + 0.25 * carry_concentration.loc[rb]
        + 0.20 * pace.loc[rb]
        + 0.15 * (1.0 - red_zone_pass.loc[rb])
        + 0.10 * motion.loc[rb]
    )
    score.loc[receiver] = (
        0.35 * pass_rate.loc[receiver]
        + 0.20 * pace.loc[receiver]
        + 0.20 * target_concentration.loc[receiver]
        + 0.15 * shotgun.loc[receiver]
        + 0.10 * motion.loc[receiver]
    )
    data["scheme_fit_score"] = score.clip(0, 1)
    data["scheme_pass_environment"] = pass_rate
    data["scheme_pace_environment"] = pace
    data["scheme_target_concentration"] = target_concentration
    data["scheme_carry_concentration"] = carry_concentration

    role_target = pd.to_numeric(
        data["history_actual_target_share_roll3_mean"]
        if "history_actual_target_share_roll3_mean" in data
        else pd.Series(0.0, index=data.index),
        errors="coerce",
    ).fillna(0.0)
    role_carry = pd.to_numeric(
        data["history_actual_carry_share_roll3_mean"]
        if "history_actual_carry_share_roll3_mean" in data
        else pd.Series(0.0, index=data.index),
        errors="coerce",
    ).fillna(0.0)
    data["role_system_integration_score"] = (
        0.55 * data["scheme_fit_score"]
        + 0.25 * np.where(receiver, role_target.clip(0, 1), role_carry.clip(0, 1))
        + 0.20 * pace
    ).clip(0, 1)
    return data
