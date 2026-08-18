from __future__ import annotations

import numpy as np
import pandas as pd


def _chronology(frame: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(frame["season"], errors="coerce") * 100 + pd.to_numeric(
        frame["week"], errors="coerce"
    )


def _weighted_counts(
    events: pd.DataFrame,
    player_column: str,
    *,
    reference_ordinal: int,
    half_life_weeks: float,
) -> pd.DataFrame:
    subset = events.loc[events[player_column].notna()].copy()
    if subset.empty:
        return pd.DataFrame(columns=["team", "player_id", "weighted_count", "weighted_red_zone"])
    age = (reference_ordinal - _chronology(subset)).clip(lower=0)
    weights = np.power(0.5, age / max(float(half_life_weeks), 0.25))
    subset["weight"] = weights
    subset["weighted_red_zone"] = weights * pd.to_numeric(subset["red_zone"], errors="coerce").fillna(0.0)
    subset["player_id"] = subset[player_column].astype(str)
    return (
        subset.groupby(["posteam", "player_id"], dropna=False)
        .agg(weighted_count=("weight", "sum"), weighted_red_zone=("weighted_red_zone", "sum"))
        .reset_index()
        .rename(columns={"posteam": "team"})
    )


def build_player_usage_profiles(
    play_frame: pd.DataFrame,
    *,
    season: int,
    week: int,
    players: pd.DataFrame | None = None,
    lookback_weeks: int = 8,
    half_life_weeks: float = 3.0,
) -> pd.DataFrame:
    """Build point-in-time carry, target and dropback allocation profiles."""
    required = {"season", "week", "posteam", "rusher_player_id", "receiver_player_id"}
    missing = required - set(play_frame)
    if missing:
        raise ValueError(f"Usage profiles missing columns: {sorted(missing)}")
    reference = int(season) * 100 + int(week)
    ordinal = _chronology(play_frame)
    history = play_frame.loc[(ordinal < reference) & (ordinal >= reference - int(lookback_weeks))].copy()
    if history.empty:
        return pd.DataFrame(
            columns=[
                "team",
                "player_id",
                "position",
                "carry_share",
                "target_share",
                "dropback_share",
                "red_zone_carry_share",
                "red_zone_target_share",
                "usage_evidence_weight",
            ]
        )

    carries = _weighted_counts(
        history.loc[history["play_family"].eq("RUSH")],
        "rusher_player_id",
        reference_ordinal=reference,
        half_life_weeks=half_life_weeks,
    ).rename(columns={"weighted_count": "carry_weight", "weighted_red_zone": "rz_carry_weight"})
    targets = _weighted_counts(
        history.loc[history["play_family"].eq("DROPBACK")],
        "receiver_player_id",
        reference_ordinal=reference,
        half_life_weeks=half_life_weeks,
    ).rename(columns={"weighted_count": "target_weight", "weighted_red_zone": "rz_target_weight"})
    passer_column = "passer_player_id" if "passer_player_id" in history else "receiver_player_id"
    dropbacks = _weighted_counts(
        history.loc[history["play_family"].eq("DROPBACK")],
        passer_column,
        reference_ordinal=reference,
        half_life_weeks=half_life_weeks,
    ).rename(columns={"weighted_count": "dropback_weight"})[["team", "player_id", "dropback_weight"]]

    profile = carries.merge(targets, on=["team", "player_id"], how="outer")
    profile = profile.merge(dropbacks, on=["team", "player_id"], how="outer")
    for column in (
        "carry_weight",
        "rz_carry_weight",
        "target_weight",
        "rz_target_weight",
        "dropback_weight",
    ):
        if column not in profile:
            profile[column] = 0.0
        profile[column] = pd.to_numeric(profile[column], errors="coerce").fillna(0.0)

    def share(column: str) -> pd.Series:
        denominator = profile.groupby("team", sort=False)[column].transform("sum").replace(0, np.nan)
        return (profile[column] / denominator).fillna(0.0)

    profile["carry_share"] = share("carry_weight")
    profile["target_share"] = share("target_weight")
    profile["dropback_share"] = share("dropback_weight")
    profile["red_zone_carry_share"] = share("rz_carry_weight")
    profile["red_zone_target_share"] = share("rz_target_weight")
    profile["usage_evidence_weight"] = profile[
        ["carry_weight", "target_weight", "dropback_weight"]
    ].sum(axis=1)
    profile["position"] = "UNK"

    if players is not None and not players.empty:
        player_frame = players.copy()
        id_column = next(
            (column for column in ("gsis_id", "player_id", "canonical_player_id") if column in player_frame),
            None,
        )
        if id_column and "position" in player_frame:
            mapping = (
                player_frame[[id_column, "position"]]
                .dropna(subset=[id_column])
                .drop_duplicates(id_column)
                .rename(columns={id_column: "player_id", "position": "position_mapped"})
            )
            mapping["player_id"] = mapping["player_id"].astype(str)
            profile = profile.merge(mapping, on="player_id", how="left", validate="many_to_one")
            profile["position"] = profile["position_mapped"].fillna(profile["position"])
            profile = profile.drop(columns="position_mapped")

    columns = [
        "team",
        "player_id",
        "position",
        "carry_share",
        "target_share",
        "dropback_share",
        "red_zone_carry_share",
        "red_zone_target_share",
        "usage_evidence_weight",
    ]
    return profile.loc[:, columns].sort_values(
        ["team", "usage_evidence_weight"], ascending=[True, False], kind="mergesort"
    ).reset_index(drop=True)
