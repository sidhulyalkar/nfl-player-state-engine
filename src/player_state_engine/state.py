from __future__ import annotations

import pandas as pd


def latest_player_states(feature_frame: pd.DataFrame) -> pd.DataFrame:
    """Export the newest pregame state vector for each player."""
    actual_mask = (
        ~feature_frame["is_projection_row"].astype(bool)
        if "is_projection_row" in feature_frame
        else pd.Series(True, index=feature_frame.index)
    )
    actual = feature_frame.loc[actual_mask].copy()
    actual = actual.sort_values(["season", "week", "game_id"])
    latest = actual.groupby("player_id", as_index=False).tail(1)
    context = [
        column
        for column in (
            "season",
            "week",
            "player_id",
            "player_name",
            "recent_team",
            "position",
            "player_history_count",
        )
        if column in latest
    ]
    state_columns = [
        column
        for column in latest.columns
        if any(
            token in column
            for token in ("_lag1", "_roll", "_ewm_", "position_", "team_", "opp_allowed_")
        )
    ]
    return latest[context + state_columns].reset_index(drop=True)
