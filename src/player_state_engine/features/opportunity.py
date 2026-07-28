from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

OPPORTUNITY_TARGETS = (
    "opportunity_active",
    "opportunity_snap_share",
    "opportunity_route_participation",
    "opportunity_team_plays",
    "opportunity_team_dropbacks",
    "opportunity_carry_share",
    "opportunity_target_share",
    "opportunity_red_zone_share",
    "carries",
    "targets",
    "receptions",
    "receiving_yards",
    "rushing_yards",
    "passing_yards",
    "opportunity_total_touchdowns",
    "fantasy_points_ppr",
)


def _num(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def derive_opportunity_targets(frame: pd.DataFrame) -> pd.DataFrame:
    """Create same-week supervision labels for the causal opportunity ladder.

    These columns are targets only. They must never be admitted by the pregame
    feature selector without a lag/rolling suffix.
    """

    data = frame.copy()
    keys = ["season", "week", "recent_team"]
    missing = set(keys) - set(data.columns)
    if missing:
        raise ValueError(f"Opportunity targets require columns: {sorted(missing)}")

    attempts = _num(data, "passing_attempts").fillna(0.0)
    carries = _num(data, "carries").fillna(0.0)
    targets = _num(data, "targets").fillna(0.0)
    receptions = _num(data, "receptions").fillna(0.0)
    snap_count = _num(data, "snap_count", np.nan)
    route_count = _num(data, "route_count", np.nan)
    if "snap_count_available" in data:
        snap_count = snap_count.where(
            pd.to_numeric(data["snap_count_available"], errors="coerce").fillna(0).gt(0)
        )
    if "route_count_available" in data:
        route_count = route_count.where(
            pd.to_numeric(data["route_count_available"], errors="coerce").fillna(0).gt(0)
        )

    team_attempts = attempts.groupby([data[k] for k in keys]).transform("sum")
    team_carries = carries.groupby([data[k] for k in keys]).transform("sum")
    team_targets = targets.groupby([data[k] for k in keys]).transform("sum")
    team_plays = team_attempts + team_carries

    data["opportunity_active"] = (
        (attempts + carries + targets + receptions > 0)
        | snap_count.fillna(0).gt(0)
        | route_count.fillna(0).gt(0)
    ).astype(float)
    data["opportunity_team_dropbacks"] = team_attempts
    data["opportunity_team_plays"] = team_plays
    data["opportunity_carry_share"] = np.where(team_carries > 0, carries / team_carries, 0.0)
    data["opportunity_target_share"] = np.where(team_targets > 0, targets / team_targets, 0.0)

    team_snaps = snap_count.groupby([data[k] for k in keys]).transform("max")
    data["opportunity_snap_share"] = np.where(team_snaps > 0, snap_count / team_snaps, np.nan)
    data["opportunity_route_participation"] = np.where(
        team_attempts > 0, route_count / team_attempts, np.nan
    )

    rz_carries = _num(data, "carries_inside_10", np.nan)
    rz_targets = _num(data, "targets_inside_10", np.nan)
    rz = rz_carries.fillna(0.0) + rz_targets.fillna(0.0)
    team_rz = rz.groupby([data[k] for k in keys]).transform("sum")
    has_rz = rz_carries.notna() | rz_targets.notna()
    data["opportunity_red_zone_share"] = np.where(has_rz & team_rz.gt(0), rz / team_rz, np.nan)
    data["opportunity_total_touchdowns"] = (
        _num(data, "passing_tds").fillna(0.0)
        + _num(data, "rushing_tds").fillna(0.0)
        + _num(data, "receiving_tds").fillna(0.0)
    )
    return data


def add_roster_transition_features(
    frame: pd.DataFrame,
    offensive_line: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Add point-in-time rookie, team-change, QB-change and OL continuity context."""

    data = frame.sort_values(["player_id", "season", "week"]).copy()
    grouped = data.groupby("player_id", sort=False)
    first_season = grouped["season"].transform("min")
    data["is_rookie_prior"] = data["season"].eq(first_season).astype(int)
    previous_team = grouped["recent_team"].shift(1)
    data["team_changed_prior"] = (
        previous_team.notna().mul(previous_team.ne(data["recent_team"])).astype(int)
    )

    actual = data.loc[~data.get("is_projection_row", False).astype(bool)].copy()
    qb = actual.loc[actual["position"].eq("QB")].copy()
    if not qb.empty:
        volume = pd.to_numeric(qb.get("passing_attempts", 0.0), errors="coerce").fillna(0.0)
        qb = qb.assign(_volume=volume).sort_values(
            ["season", "week", "recent_team", "_volume"], ascending=[True, True, True, False]
        )
        primary = qb.groupby(["season", "week", "recent_team"], as_index=False).first()
        primary = primary.sort_values(["recent_team", "season", "week"])
        primary["previous_primary_qb"] = primary.groupby("recent_team")["player_id"].shift(1)
        primary["two_games_ago_primary_qb"] = primary.groupby("recent_team")["player_id"].shift(2)
        primary["quarterback_changed_prior"] = (
            primary["previous_primary_qb"].notna()
            & primary["two_games_ago_primary_qb"].notna()
            & primary["previous_primary_qb"].ne(primary["two_games_ago_primary_qb"])
        ).astype(int)
        context = primary[
            ["season", "week", "recent_team", "previous_primary_qb", "quarterback_changed_prior"]
        ]
        data = data.merge(
            context, on=["season", "week", "recent_team"], how="left", validate="many_to_one"
        )
    else:
        data["previous_primary_qb"] = pd.NA
        data["quarterback_changed_prior"] = 0

    if offensive_line is not None and not offensive_line.empty:
        required = {"season", "week", "recent_team", "ol_continuity"}
        missing = required - set(offensive_line.columns)
        if missing:
            raise ValueError(f"Offensive-line context missing columns: {sorted(missing)}")
        ol = offensive_line[list(required)].copy()
        data = data.merge(
            ol, on=["season", "week", "recent_team"], how="left", validate="many_to_one"
        )
    elif "ol_continuity" not in data:
        data["ol_continuity"] = np.nan
    data["ol_continuity_missing"] = data["ol_continuity"].isna().astype(int)
    return data


def add_opportunity_history_features(
    frame: pd.DataFrame,
    *,
    windows: Iterable[int] = (3, 5, 8),
) -> pd.DataFrame:
    data = derive_opportunity_targets(frame)
    data = data.sort_values(["player_id", "season", "week", "game_id"]).copy()
    grouped = data.groupby("player_id", sort=False)
    generated: dict[str, pd.Series] = {}
    for column in (name for name in OPPORTUNITY_TARGETS if name.startswith("opportunity_")):
        if column not in data:
            continue
        shifted = grouped[column].shift(1)
        generated[f"{column}_lag1"] = shifted
        shifted_group = shifted.groupby(data["player_id"], sort=False)
        for window in windows:
            generated[f"{column}_roll{window}_mean"] = (
                shifted_group.rolling(window, min_periods=1)
                .mean()
                .reset_index(level=0, drop=True)
                .reindex(data.index)
            )
            generated[f"{column}_roll{window}_std"] = (
                shifted_group.rolling(window, min_periods=1)
                .std(ddof=0)
                .reset_index(level=0, drop=True)
                .reindex(data.index)
            )
    return pd.concat([data, pd.DataFrame(generated, index=data.index)], axis=1)
