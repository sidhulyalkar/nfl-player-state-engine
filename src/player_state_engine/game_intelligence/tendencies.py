from __future__ import annotations

import numpy as np
import pandas as pd


_OFFENSE_ACTUALS = (
    "plays",
    "pass_rate",
    "neutral_pass_rate",
    "early_down_pass_rate",
    "red_zone_pass_rate",
    "third_down_pass_rate",
    "shotgun_rate",
    "no_huddle_rate",
    "motion_rate",
    "play_action_rate",
    "rpo_rate",
    "screen_rate",
    "seconds_between_plays",
    "epa_per_play",
    "explosive_rate",
    "fourth_down_scrimmage_rate",
)


def _rate(group: pd.DataFrame, mask: pd.Series, column: str) -> float:
    subset = group.loc[mask]
    if subset.empty:
        return np.nan
    return float(pd.to_numeric(subset[column], errors="coerce").mean())


def _weekly_team_actuals(play_frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (season, week, team), group in play_frame.groupby(
        ["season", "week", "posteam"], sort=True, dropna=False
    ):
        neutral = group["neutral_score_state"].eq(1) & group["qtr"].le(3)
        early = group["down"].isin([1, 2])
        red_zone = group["red_zone"].eq(1)
        third = group["down"].eq(3)
        fourth = group["down"].eq(4)
        rows.append(
            {
                "season": int(season),
                "week": int(week),
                "team": str(team),
                "plays_actual": float(len(group)),
                "pass_rate_actual": float(group["is_dropback"].mean()),
                "neutral_pass_rate_actual": _rate(group, neutral, "is_dropback"),
                "early_down_pass_rate_actual": _rate(group, early, "is_dropback"),
                "red_zone_pass_rate_actual": _rate(group, red_zone, "is_dropback"),
                "third_down_pass_rate_actual": _rate(group, third, "is_dropback"),
                "shotgun_rate_actual": float(group["shotgun_flag"].mean()),
                "no_huddle_rate_actual": float(group["no_huddle_flag"].mean()),
                "motion_rate_actual": float(group["motion_flag"].mean()),
                "play_action_rate_actual": float(group["play_action_flag"].mean()),
                "rpo_rate_actual": float(group["rpo_flag"].mean()),
                "screen_rate_actual": float(group["screen_flag"].mean()),
                "seconds_between_plays_actual": float(group["seconds_between_plays"].median())
                if group["seconds_between_plays"].notna().any()
                else np.nan,
                "epa_per_play_actual": float(group["epa"].mean()),
                "explosive_rate_actual": float(group["explosive_play"].mean()),
                "fourth_down_scrimmage_rate_actual": float(fourth.mean()),
            }
        )
    return pd.DataFrame(rows)


def _weekly_defense_actuals(play_frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (season, week, team), group in play_frame.groupby(
        ["season", "week", "defteam"], sort=True, dropna=False
    ):
        neutral = group["neutral_score_state"].eq(1) & group["qtr"].le(3)
        rows.append(
            {
                "season": int(season),
                "week": int(week),
                "team": str(team),
                "defense_plays_actual": float(len(group)),
                "defense_pass_rate_faced_actual": float(group["is_dropback"].mean()),
                "defense_neutral_pass_rate_faced_actual": _rate(group, neutral, "is_dropback"),
                "defense_epa_allowed_actual": float(group["epa"].mean()),
                "defense_explosive_allowed_actual": float(group["explosive_play"].mean()),
                "defense_turnover_rate_actual": float(group["turnover"].mean()),
                "defense_red_zone_rate_actual": float(group["red_zone"].mean()),
            }
        )
    return pd.DataFrame(rows)


def _add_point_in_time_history(frame: pd.DataFrame, span: int = 6) -> pd.DataFrame:
    data = frame.sort_values(["team", "season", "week"], kind="mergesort").copy()
    actuals = [column for column in data if column.endswith("_actual")]
    for column in actuals:
        shifted = data.groupby("team", sort=False)[column].shift(1)
        data[column.replace("_actual", "_lag1")] = shifted
        data[column.replace("_actual", f"_ewm{span}")] = shifted.groupby(
            data["team"], sort=False
        ).transform(lambda values: values.ewm(span=span, adjust=False, min_periods=1).mean())
    return data


def build_team_tendency_snapshots(play_frame: pd.DataFrame, *, span: int = 6) -> pd.DataFrame:
    """Create leakage-safe offense and defense tendency snapshots for every team-week."""
    required = {"season", "week", "posteam", "defteam", "is_dropback"}
    missing = required - set(play_frame)
    if missing:
        raise ValueError(f"Tendency snapshots missing columns: {sorted(missing)}")
    offense = _add_point_in_time_history(_weekly_team_actuals(play_frame), span=span)
    defense = _add_point_in_time_history(_weekly_defense_actuals(play_frame), span=span)
    merged = offense.merge(defense, on=["season", "week", "team"], how="outer", validate="one_to_one")
    return merged.sort_values(["season", "week", "team"], kind="mergesort").reset_index(drop=True)


def build_coaching_matchup_history(
    play_frame: pd.DataFrame,
    coaches: pd.DataFrame,
    *,
    max_weight: float = 0.20,
) -> pd.DataFrame:
    """Build heavily-shrunk point-in-time play-caller matchup history.

    The table is intentionally low authority because direct coach-vs-coach samples are sparse.
    ``coach_matchup_weight`` cannot exceed ``max_weight`` and is based only on prior games.
    """
    required = {"season", "team", "offensive_play_caller", "defensive_play_caller"}
    missing = required - set(coaches)
    if missing:
        raise ValueError(f"Coaching metadata missing: {sorted(missing)}")
    coach = coaches.copy()
    if "week" not in coach:
        coach["week"] = 0
    offense = coach.rename(
        columns={"team": "posteam", "offensive_play_caller": "offensive_play_caller_id"}
    )[["season", "week", "posteam", "offensive_play_caller_id"]]
    defense = coach.rename(
        columns={"team": "defteam", "defensive_play_caller": "defensive_play_caller_id"}
    )[["season", "week", "defteam", "defensive_play_caller_id"]]
    data = play_frame.copy()
    if coach["week"].eq(0).all():
        offense = offense.drop(columns="week").drop_duplicates(["season", "posteam"])
        defense = defense.drop(columns="week").drop_duplicates(["season", "defteam"])
        data = data.merge(offense, on=["season", "posteam"], how="left", validate="many_to_one")
        data = data.merge(defense, on=["season", "defteam"], how="left", validate="many_to_one")
    else:
        data = data.merge(offense, on=["season", "week", "posteam"], how="left", validate="many_to_one")
        data = data.merge(defense, on=["season", "week", "defteam"], how="left", validate="many_to_one")

    game = (
        data.dropna(subset=["offensive_play_caller_id", "defensive_play_caller_id"])
        .groupby(
            ["season", "week", "game_id", "offensive_play_caller_id", "defensive_play_caller_id"],
            dropna=False,
        )
        .agg(pass_rate=("is_dropback", "mean"), plays=("play_id", "size"))
        .reset_index()
        .sort_values(["season", "week", "game_id"], kind="mergesort")
    )
    if game.empty:
        return game
    pair = ["offensive_play_caller_id", "defensive_play_caller_id"]
    game["coach_matchup_games_prior"] = game.groupby(pair, sort=False).cumcount()
    prior_sum = game.groupby(pair, sort=False)["pass_rate"].cumsum() - game["pass_rate"]
    game["coach_matchup_pass_rate_prior"] = prior_sum / game["coach_matchup_games_prior"].replace(0, np.nan)
    game["coach_matchup_weight"] = (
        game["coach_matchup_games_prior"].astype(float).mul(0.025).clip(upper=float(max_weight))
    )
    return game


def _latest_snapshot(
    snapshots: pd.DataFrame,
    *,
    season: int,
    week: int,
    team: str,
) -> pd.Series | None:
    eligible = snapshots.loc[
        (pd.to_numeric(snapshots["season"], errors="coerce") == int(season))
        & (pd.to_numeric(snapshots["week"], errors="coerce") <= int(week))
        & snapshots["team"].astype(str).eq(str(team))
    ].sort_values("week")
    if eligible.empty:
        return None
    return eligible.iloc[-1]


def build_matchup_profile(
    snapshots: pd.DataFrame,
    *,
    season: int,
    week: int,
    offense_team: str,
    defense_team: str,
    coach_matchup: pd.Series | None = None,
) -> dict[str, float | str]:
    """Blend offense, defense and league priors into a pregame matchup profile."""
    offense = _latest_snapshot(snapshots, season=season, week=week, team=offense_team)
    defense = _latest_snapshot(snapshots, season=season, week=week, team=defense_team)
    league = snapshots.loc[
        (pd.to_numeric(snapshots["season"], errors="coerce") == int(season))
        & (pd.to_numeric(snapshots["week"], errors="coerce") <= int(week))
    ]

    def value(row: pd.Series | None, column: str, default: float) -> float:
        if row is None or column not in row or pd.isna(row[column]):
            return default
        return float(row[column])

    league_pass = float(pd.to_numeric(league.get("pass_rate_ewm6"), errors="coerce").mean())
    if not np.isfinite(league_pass):
        league_pass = 0.58
    offense_pass = value(offense, "pass_rate_ewm6", league_pass)
    defense_pass = value(defense, "defense_pass_rate_faced_ewm6", league_pass)
    pass_rate = 0.62 * offense_pass + 0.28 * defense_pass + 0.10 * league_pass
    coach_weight = 0.0
    if coach_matchup is not None:
        coach_rate = pd.to_numeric(coach_matchup.get("coach_matchup_pass_rate_prior"), errors="coerce")
        coach_weight = float(pd.to_numeric(coach_matchup.get("coach_matchup_weight", 0.0), errors="coerce"))
        if pd.notna(coach_rate) and coach_weight > 0:
            pass_rate = (1.0 - coach_weight) * pass_rate + coach_weight * float(coach_rate)

    pace_default = 28.0
    return {
        "offense_team": str(offense_team),
        "defense_team": str(defense_team),
        "pregame_pass_rate": float(np.clip(pass_rate, 0.30, 0.82)),
        "offense_pass_rate": offense_pass,
        "defense_pass_rate_faced": defense_pass,
        "neutral_pass_rate": value(offense, "neutral_pass_rate_ewm6", pass_rate),
        "early_down_pass_rate": value(offense, "early_down_pass_rate_ewm6", pass_rate),
        "red_zone_pass_rate": value(offense, "red_zone_pass_rate_ewm6", pass_rate),
        "third_down_pass_rate": value(offense, "third_down_pass_rate_ewm6", pass_rate),
        "seconds_between_plays": value(offense, "seconds_between_plays_ewm6", pace_default),
        "epa_per_play": value(offense, "epa_per_play_ewm6", 0.0),
        "defense_epa_allowed": value(defense, "defense_epa_allowed_ewm6", 0.0),
        "explosive_rate": value(offense, "explosive_rate_ewm6", 0.10),
        "defense_explosive_allowed": value(defense, "defense_explosive_allowed_ewm6", 0.10),
        "coach_matchup_weight": coach_weight,
    }
