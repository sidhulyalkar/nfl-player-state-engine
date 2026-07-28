from __future__ import annotations

import pandas as pd

from player_state_engine.product.schemas import NFLStateSnapshot, NFLTeamState


def build_nfl_state(
    schedules: pd.DataFrame, season: int, through_week: int | None = None
) -> NFLStateSnapshot:
    data = schedules.copy()
    data = data.loc[pd.to_numeric(data.get("season"), errors="coerce").eq(season)]
    if through_week is not None and "week" in data:
        data = data.loc[pd.to_numeric(data["week"], errors="coerce").le(through_week)]
    if "game_type" in data:
        data = data.loc[data["game_type"].astype(str).eq("REG")]
    home_score_col = next(
        (column for column in ("home_score", "home_points") if column in data), None
    )
    away_score_col = next(
        (column for column in ("away_score", "away_points") if column in data), None
    )
    if not home_score_col or not away_score_col:
        raise ValueError("Schedules require home_score/home_points and away_score/away_points")
    completed = data.loc[data[home_score_col].notna() & data[away_score_col].notna()].copy()
    teams = sorted(set(completed.get("home_team", [])) | set(completed.get("away_team", [])))
    rows: list[NFLTeamState] = []
    for team in teams:
        games = completed.loc[
            completed["home_team"].eq(team) | completed["away_team"].eq(team)
        ].sort_values("week")
        wins = losses = ties = 0
        points_for = points_against = 0.0
        outcomes: list[str] = []
        for _, game in games.iterrows():
            is_home = game["home_team"] == team
            own = float(game[home_score_col] if is_home else game[away_score_col])
            opponent = float(game[away_score_col] if is_home else game[home_score_col])
            points_for += own
            points_against += opponent
            if own > opponent:
                wins += 1
                outcomes.append("W")
            elif own < opponent:
                losses += 1
                outcomes.append("L")
            else:
                ties += 1
                outcomes.append("T")
        streak = None
        if outcomes:
            latest = outcomes[-1]
            count = 0
            for outcome in reversed(outcomes):
                if outcome != latest:
                    break
                count += 1
            streak = f"{latest}{count}"
        games_played = wins + losses + ties
        rows.append(
            NFLTeamState(
                team=str(team),
                wins=wins,
                losses=losses,
                ties=ties,
                points_for=points_for,
                points_against=points_against,
                point_differential=points_for - points_against,
                win_percentage=(wins + 0.5 * ties) / games_played if games_played else 0.0,
                streak=streak,
            )
        )
    rows.sort(key=lambda team: (team.win_percentage, team.point_differential), reverse=True)
    return NFLStateSnapshot(
        season=season,
        week=through_week,
        teams=rows,
        metadata={"completed_games": len(completed)},
    )
