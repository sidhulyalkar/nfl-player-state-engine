from __future__ import annotations

import numpy as np
import pandas as pd


def _ordinal(season: object, week: object) -> float:
    season_value = pd.to_numeric(season, errors="coerce")
    week_value = pd.to_numeric(week, errors="coerce")
    if pd.isna(season_value) or pd.isna(week_value):
        return float("nan")
    return float(season_value) * 25.0 + float(week_value)


def resolve_team_play_callers(
    coaches: pd.DataFrame,
    *,
    season: int,
    week: int,
    team: str,
) -> dict[str, str | None]:
    """Resolve the latest verified play callers that were known by the target week."""
    required = {"season", "team", "offensive_play_caller", "defensive_play_caller"}
    missing = required - set(coaches)
    if missing:
        raise ValueError(f"Coaching registry missing columns: {sorted(missing)}")
    data = coaches.copy()
    if "week" not in data:
        data["week"] = 0
    target = _ordinal(season, week)
    data["_ordinal"] = [
        _ordinal(row_season, row_week)
        for row_season, row_week in zip(data["season"], data["week"], strict=False)
    ]
    eligible = data.loc[
        data["team"].astype(str).eq(str(team))
        & data["_ordinal"].notna()
        & data["_ordinal"].le(target)
    ].sort_values(["_ordinal"], kind="mergesort")
    if eligible.empty:
        return {"offensive_play_caller": None, "defensive_play_caller": None}
    row = eligible.iloc[-1]
    offensive = row.get("offensive_play_caller")
    defensive = row.get("defensive_play_caller")
    return {
        "offensive_play_caller": None if pd.isna(offensive) else str(offensive),
        "defensive_play_caller": None if pd.isna(defensive) else str(defensive),
    }


def resolve_coach_matchup_prior(
    history: pd.DataFrame,
    *,
    offensive_play_caller: str | None,
    defensive_play_caller: str | None,
    season: int,
    week: int,
    max_weight: float = 0.20,
) -> pd.Series | None:
    """Aggregate completed prior meetings for one play-caller pair with heavy shrinkage."""
    if history.empty or not offensive_play_caller or not defensive_play_caller:
        return None
    required = {
        "season",
        "week",
        "offensive_play_caller_id",
        "defensive_play_caller_id",
        "pass_rate",
    }
    missing = required - set(history)
    if missing:
        raise ValueError(f"Coach matchup history missing columns: {sorted(missing)}")
    target = _ordinal(season, week)
    data = history.copy()
    data["_ordinal"] = [
        _ordinal(row_season, row_week)
        for row_season, row_week in zip(data["season"], data["week"], strict=False)
    ]
    prior = data.loc[
        data["offensive_play_caller_id"].astype(str).eq(str(offensive_play_caller))
        & data["defensive_play_caller_id"].astype(str).eq(str(defensive_play_caller))
        & data["_ordinal"].notna()
        & data["_ordinal"].lt(target)
    ]
    if prior.empty:
        return None
    pass_rate = pd.to_numeric(prior["pass_rate"], errors="coerce").dropna()
    if pass_rate.empty:
        return None
    games = int(prior["game_id"].nunique()) if "game_id" in prior else int(len(prior))
    weight = min(float(max_weight), 0.025 * games)
    return pd.Series(
        {
            "offensive_play_caller_id": offensive_play_caller,
            "defensive_play_caller_id": defensive_play_caller,
            "coach_matchup_games_prior": games,
            "coach_matchup_pass_rate_prior": float(pass_rate.mean()),
            "coach_matchup_weight": float(np.clip(weight, 0.0, max_weight)),
        }
    )


def resolve_game_coach_priors(
    coaches: pd.DataFrame | None,
    history: pd.DataFrame | None,
    *,
    season: int,
    week: int,
    home_team: str,
    away_team: str,
) -> dict[str, pd.Series | None]:
    """Resolve both offenses' current-caller vs opposing-caller priors for a matchup."""
    if coaches is None or coaches.empty or history is None or history.empty:
        return {home_team: None, away_team: None}
    home_callers = resolve_team_play_callers(coaches, season=season, week=week, team=home_team)
    away_callers = resolve_team_play_callers(coaches, season=season, week=week, team=away_team)
    return {
        home_team: resolve_coach_matchup_prior(
            history,
            offensive_play_caller=home_callers["offensive_play_caller"],
            defensive_play_caller=away_callers["defensive_play_caller"],
            season=season,
            week=week,
        ),
        away_team: resolve_coach_matchup_prior(
            history,
            offensive_play_caller=away_callers["offensive_play_caller"],
            defensive_play_caller=home_callers["defensive_play_caller"],
            season=season,
            week=week,
        ),
    }
