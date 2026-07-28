from __future__ import annotations

from datetime import timedelta

import pandas as pd

INTELLIGENCE_PREFIXES = ("availability_", "news_", "persona_")


def attach_point_in_time_intelligence(
    football_features: pd.DataFrame,
    intelligence_features: pd.DataFrame,
    kickoff_column: str = "gameday",
    as_of_column: str = "as_of_utc",
    safety_lag_hours: int = 1,
) -> pd.DataFrame:
    """Attach the latest player intelligence snapshot known before kickoff.

    The safety lag protects against same-time publication ambiguity and ensures
    that text collected after kickoff cannot enter the prediction row.
    """

    if kickoff_column not in football_features.columns:
        raise ValueError(
            f"Football features require {kickoff_column!r} for point-in-time attachment."
        )
    required = {"player_id", as_of_column}
    missing = required - set(intelligence_features.columns)
    if missing:
        raise ValueError(f"Intelligence table missing required columns: {sorted(missing)}")

    left = football_features.copy()
    right = intelligence_features.copy()
    left["_intelligence_cutoff"] = pd.to_datetime(
        left[kickoff_column], utc=True, errors="coerce"
    ) - timedelta(hours=safety_lag_hours)
    right[as_of_column] = pd.to_datetime(right[as_of_column], utc=True, errors="coerce")
    left["player_id"] = left["player_id"].astype(str)
    right["player_id"] = right["player_id"].astype(str)
    left["_row_order"] = range(len(left))
    left = left.sort_values(["player_id", "_intelligence_cutoff"])
    right = right.sort_values(["player_id", as_of_column])
    joined = pd.merge_asof(
        left,
        right,
        left_on="_intelligence_cutoff",
        right_on=as_of_column,
        by="player_id",
        direction="backward",
        allow_exact_matches=True,
        suffixes=("", "_intel"),
    )
    intelligence_columns = [
        column for column in joined.columns if column.startswith(INTELLIGENCE_PREFIXES)
    ]
    joined[intelligence_columns] = joined[intelligence_columns].fillna(0.0)
    joined["intelligence_snapshot_found"] = joined[as_of_column].notna().astype(int)
    return (
        joined.sort_values("_row_order")
        .drop(columns=["_row_order", "_intelligence_cutoff"])
        .reset_index(drop=True)
    )


def attach_intelligence_families(
    football_features: pd.DataFrame,
    families: dict[str, pd.DataFrame],
    *,
    kickoff_column: str = "gameday",
    safety_lag_hours: int = 1,
) -> pd.DataFrame:
    """Attach multiple snapshot families without timestamp-column collisions."""

    result = football_features.copy()
    for family, snapshots in families.items():
        if not family.replace("_", "").isalnum():
            raise ValueError(f"Unsafe intelligence family name: {family!r}")
        right = snapshots.copy()
        if "as_of_utc" not in right:
            raise ValueError(f"Intelligence family {family!r} is missing 'as_of_utc'.")
        family_as_of = f"{family}_as_of_utc"
        right = right.rename(columns={"as_of_utc": family_as_of})
        result = attach_point_in_time_intelligence(
            result,
            right,
            kickoff_column=kickoff_column,
            as_of_column=family_as_of,
            safety_lag_hours=safety_lag_hours,
        )
        result = result.rename(columns={"intelligence_snapshot_found": f"{family}_snapshot_found"})
    return result
