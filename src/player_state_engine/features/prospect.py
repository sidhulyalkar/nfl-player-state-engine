from __future__ import annotations

import re

import numpy as np
import pandas as pd

COMBINE_ALIASES = {
    "player_name": ("player_name", "pfr_name", "name"),
    "draft_year": ("season", "draft_year", "year"),
    "position": ("pos", "position"),
    "forty": ("forty", "forty_yard", "forty_time"),
    "bench": ("bench", "bench_reps"),
    "vertical": ("vertical", "vertical_jump"),
    "broad_jump": ("broad_jump", "broad"),
    "cone": ("cone", "three_cone"),
    "shuttle": ("shuttle", "short_shuttle"),
    "height": ("height",),
    "weight": ("weight",),
}

COLLEGE_ALIASES = {
    "player_name": ("player_name", "name"),
    "draft_year": ("draft_year", "season", "year"),
    "position": ("position", "pos"),
    "age": ("age", "draft_age"),
    "breakout_age": ("breakout_age",),
    "dominator_rating": ("dominator_rating", "college_dominator"),
    "college_target_share": ("college_target_share", "target_share"),
    "college_rush_share": ("college_rush_share", "rush_share"),
    "yards_per_team_pass_attempt": (
        "yards_per_team_pass_attempt",
        "college_yards_per_team_pass_attempt",
        "yptpa",
    ),
    "career_receiving_yards": ("career_receiving_yards", "receiving_yards"),
    "career_rushing_yards": ("career_rushing_yards", "rushing_yards"),
    "career_touchdowns": ("career_touchdowns", "touchdowns"),
    "early_declare": ("early_declare",),
}


def _first(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    return next((n for n in names if n in frame), None)


def _normalize_name(value: object) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", str(value).lower())
    return " ".join(text.split())


def canonicalize_combine(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    for target, aliases in COMBINE_ALIASES.items():
        source = _first(frame, aliases)
        out[target] = frame[source] if source else np.nan
    out["player_name"] = out["player_name"].astype(str)
    out["name_key"] = out["player_name"].map(_normalize_name)
    out["position"] = out["position"].fillna("UNK").astype(str).str.upper()
    for column in set(out) - {"player_name", "name_key", "position"}:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def add_combine_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """Add position-standardized athletic and size scores without future outcomes."""
    data = canonicalize_combine(frame)
    data["combine_speed_score"] = (
        data["weight"] * (200.0 / data["forty"].clip(lower=3.5)) ** 4 / 100.0
    )
    data["combine_burst_raw"] = data["vertical"] + data["broad_jump"] / 10.0
    data["combine_agility_raw"] = -(data["cone"] + data["shuttle"])
    for column in (
        "combine_speed_score",
        "combine_burst_raw",
        "combine_agility_raw",
        "weight",
        "height",
    ):
        mean = data.groupby("position")[column].transform("mean")
        std = data.groupby("position")[column].transform("std").replace(0, np.nan)
        data[f"{column}_position_z"] = (data[column] - mean) / std
    data["combine_completeness"] = (
        data[["forty", "vertical", "broad_jump", "cone", "shuttle", "bench"]].notna().mean(axis=1)
    )
    return data


def canonicalize_draft(frame: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "player_name": ("pfr_player_name", "player_name", "name"),
        "draft_year": ("season", "draft_year", "year"),
        "draft_round": ("round", "draft_round"),
        "draft_pick": ("pick", "draft_pick"),
        "draft_team": ("team", "draft_team"),
        "position": ("position", "pos"),
        "college": ("college",),
    }
    out = pd.DataFrame(index=frame.index)
    for target, names in aliases.items():
        source = _first(frame, names)
        out[target] = frame[source] if source else np.nan
    for column in ("draft_year", "draft_round", "draft_pick"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["player_name"] = out["player_name"].astype(str)
    out["name_key"] = out["player_name"].map(_normalize_name)
    out["position"] = out["position"].fillna("UNK").astype(str).str.upper()
    out["draft_capital_score"] = np.exp(-out["draft_pick"].fillna(300) / 75.0)
    out["day_one_pick"] = out["draft_round"].eq(1).astype(int)
    out["day_two_pick"] = out["draft_round"].isin([2, 3]).astype(int)
    out["undrafted_or_late"] = out["draft_round"].fillna(8).ge(6).astype(int)
    return out


def canonicalize_college_production(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    for target, names in COLLEGE_ALIASES.items():
        source = _first(frame, names)
        out[target] = frame[source] if source else np.nan
    out["player_name"] = out["player_name"].astype(str)
    out["name_key"] = out["player_name"].map(_normalize_name)
    out["position"] = out["position"].fillna("UNK").astype(str).str.upper()
    for column in set(out) - {"player_name", "name_key", "position"}:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    # Accept either fractions or percentages from user-provided datasets.
    for column in ("dominator_rating", "college_target_share", "college_rush_share"):
        median = out[column].dropna().median()
        if pd.notna(median) and median > 1.5:
            out[column] /= 100.0
    return out


def add_college_production_scores(frame: pd.DataFrame) -> pd.DataFrame:
    data = canonicalize_college_production(frame)
    early_breakout = -(
        data["breakout_age"] - data.groupby("position")["breakout_age"].transform("median")
    )
    production_raw = (
        0.32 * data["dominator_rating"].fillna(0)
        + 0.24 * data["college_target_share"].fillna(0)
        + 0.18 * data["college_rush_share"].fillna(0)
        + 0.16 * data["yards_per_team_pass_attempt"].fillna(0)
        + 0.06 * data["early_declare"].fillna(0)
        + 0.04 * early_breakout.fillna(0)
    )
    data["college_production_raw"] = production_raw
    mean = data.groupby("position")["college_production_raw"].transform("mean")
    std = data.groupby("position")["college_production_raw"].transform("std").replace(0, np.nan)
    data["college_production_position_z"] = (data["college_production_raw"] - mean) / std
    data["college_production_completeness"] = (
        data[
            [
                "breakout_age",
                "dominator_rating",
                "college_target_share",
                "college_rush_share",
                "yards_per_team_pass_attempt",
                "early_declare",
            ]
        ]
        .notna()
        .mean(axis=1)
    )
    return data


def build_prospect_features(
    combine: pd.DataFrame,
    draft: pd.DataFrame,
    college: pd.DataFrame | None = None,
) -> pd.DataFrame:
    combine_features = add_combine_scores(combine)
    draft_features = canonicalize_draft(draft)
    keys = ["name_key", "draft_year", "position"]
    combine_keep = [c for c in combine_features if c not in {"player_name"}]
    merged = draft_features.merge(
        combine_features[combine_keep], on=keys, how="left", suffixes=("", "_combine")
    )
    if college is not None and not college.empty:
        college_features = add_college_production_scores(college)
        college_keep = [c for c in college_features if c not in {"player_name"}]
        merged = merged.merge(
            college_features[college_keep], on=keys, how="left", suffixes=("", "_college")
        )
    else:
        merged["college_production_position_z"] = np.nan
        merged["college_production_completeness"] = 0.0

    athletic = (
        0.45 * merged["combine_speed_score_position_z"].fillna(0).clip(-2, 2) / 2
        + 0.30 * merged["combine_burst_raw_position_z"].fillna(0).clip(-2, 2) / 2
        + 0.25 * merged["combine_agility_raw_position_z"].fillna(0).clip(-2, 2) / 2
    )
    production = merged["college_production_position_z"].fillna(0).clip(-2, 2) / 2
    merged["athletic_prior_score"] = athletic
    merged["production_prior_score"] = production
    merged["prospect_prior_score"] = (
        0.58 * merged["draft_capital_score"].fillna(0) + 0.20 * athletic + 0.22 * production
    )
    merged["prospect_evidence_completeness"] = (
        0.45 * merged["combine_completeness"].fillna(0)
        + 0.35 * merged["college_production_completeness"].fillna(0)
        + 0.20 * merged["draft_pick"].notna().astype(float)
    )
    return merged
