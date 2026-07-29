from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml

from player_state_engine.data.historical import (
    aggregate_pass_play_participation,
    canonicalize_depth_charts,
    canonicalize_injuries,
    resolve_snap_player_ids,
)
from player_state_engine.evaluation.frozen_opportunity import (
    KEYS,
    _evaluate,
    _pipeline,
    build_frozen_opportunity_features,
)

HISTORICAL_FEATURE_ALLOWLIST = {
    "snap_counts": [
        "source_snap_share_lag1",
        "source_snap_share_roll3",
        "source_snap_share_trend",
        "source_snap_count_lag1",
        "source_snap_count_roll3",
    ],
    "pass_participation": [
        "source_pass_participation_lag1",
        "source_pass_participation_roll3",
        "source_pass_participation_trend",
    ],
    "depth_charts": [
        "source_depth_rank_pregame",
        "source_depth_starter_pregame",
        "source_depth_rank_roll3",
    ],
    "official_availability": [
        "official_report_availability_prior",
        "official_practice_availability_prior",
        "official_availability_prior",
        "official_injury_evidence_present",
    ],
}


@dataclass(slots=True)
class HistoricalSourceAblationResult:
    predictions: pd.DataFrame
    summary: pd.DataFrame
    season_metrics: pd.DataFrame
    position_metrics: pd.DataFrame
    feature_manifest: pd.DataFrame
    coverage: pd.DataFrame


def _rolling_prior(
    frame: pd.DataFrame,
    value: str,
    output_prefix: str,
    *,
    group: str = "player_id",
) -> pd.DataFrame:
    data = frame.sort_values([group, "season", "week"]).copy()
    values = pd.to_numeric(data[value], errors="coerce")
    shifted = values.groupby(data[group], sort=False).shift(1)
    data[f"{output_prefix}_lag1"] = shifted
    data[f"{output_prefix}_roll3"] = (
        shifted.groupby(data[group], sort=False)
        .rolling(3, min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
        .reindex(data.index)
    )
    data[f"{output_prefix}_trend"] = shifted - (
        shifted.groupby(data[group], sort=False)
        .rolling(5, min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
        .reindex(data.index)
    )
    return data


def _kickoff_cutoffs(schedules: pd.DataFrame, hours_before: float = 1.5) -> pd.DataFrame:
    """Return UTC cutoffs from nflverse's Eastern-time schedule fields.

    nflverse ``gameday`` + ``gametime`` values are US/Eastern wall-clock
    values. Parsing them as UTC moves the cutoff four or five hours early.
    Explicit timezone-bearing datetime columns remain authoritative.
    """
    games = schedules.copy()
    game_col = "game_id" if "game_id" in games else "nflverse_game_id"
    if game_col not in games:
        raise ValueError("Schedules require game_id or nflverse_game_id.")
    datetime_col = next(
        (
            column
            for column in ("kickoff", "start_time", "game_datetime", "game_date")
            if column in games
        ),
        None,
    )
    if datetime_col is not None:
        kickoff = pd.to_datetime(games[datetime_col], utc=True, errors="coerce")
    else:
        if "gameday" not in games:
            raise ValueError(
                "Schedules require a timezone-bearing kickoff column or gameday/gametime."
            )
        time = (
            games["gametime"].fillna("13:00")
            if "gametime" in games
            else pd.Series("13:00", index=games.index)
        )
        wall_clock = pd.to_datetime(
            games["gameday"].astype(str) + " " + time.astype(str),
            errors="coerce",
        )
        kickoff = wall_clock.dt.tz_localize(
            ZoneInfo("America/New_York"),
            ambiguous="NaT",
            nonexistent="shift_forward",
        ).dt.tz_convert("UTC")
    out = pd.DataFrame(
        {
            "game_id": games[game_col].astype(str),
            "prediction_cutoff": kickoff - pd.to_timedelta(hours_before, unit="h"),
        }
    )
    return out.drop_duplicates("game_id", keep="last")


def _point_in_time_depth(
    panel: pd.DataFrame,
    depth: pd.DataFrame,
    cutoffs: pd.DataFrame,
) -> pd.DataFrame:
    """Select the latest timestamped team/player depth row before each cutoff."""
    left = panel[["season", "week", "game_id", "recent_team", "player_id"]].drop_duplicates()
    left["game_id"] = left["game_id"].astype(str)
    left = left.merge(cutoffs, on="game_id", how="left", validate="many_to_one")
    right = depth[["season", "recent_team", "player_id", "observed_at", "depth_rank"]].copy()
    right["player_id"] = right["player_id"].astype("string")
    left["player_id"] = left["player_id"].astype("string")
    left["prediction_cutoff"] = left["prediction_cutoff"].astype("datetime64[ns, UTC]")
    right["observed_at"] = right["observed_at"].astype("datetime64[ns, UTC]")
    snapshot_groups = {
        keys: group.sort_values("observed_at")
        for keys, group in right.groupby(
            ["season", "recent_team", "player_id"],
            dropna=False,
            sort=False,
        )
    }

    parts: list[pd.DataFrame] = []
    for keys, panel_group in left.groupby(
        ["season", "recent_team", "player_id"], dropna=False, sort=False
    ):
        snapshots = snapshot_groups.get(keys)
        invalid_cutoff = panel_group.loc[panel_group["prediction_cutoff"].isna()].copy()
        invalid_cutoff["source_depth_observed_at"] = pd.NaT
        invalid_cutoff["source_depth_rank_pit"] = np.nan
        if not invalid_cutoff.empty:
            parts.append(invalid_cutoff)

        valid_cutoff = panel_group.loc[panel_group["prediction_cutoff"].notna()]
        if valid_cutoff.empty:
            continue
        if snapshots is None:
            valid_cutoff = valid_cutoff.copy()
            valid_cutoff["source_depth_observed_at"] = pd.NaT
            valid_cutoff["source_depth_rank_pit"] = np.nan
            parts.append(valid_cutoff)
        else:
            selected = pd.merge_asof(
                valid_cutoff.sort_values("prediction_cutoff"),
                snapshots[["observed_at", "depth_rank"]],
                left_on="prediction_cutoff",
                right_on="observed_at",
                direction="backward",
                allow_exact_matches=True,
            ).rename(
                columns={
                    "observed_at": "source_depth_observed_at",
                    "depth_rank": "source_depth_rank_pit",
                }
            )
            parts.append(selected)
    if not parts:
        return pd.DataFrame(
            columns=[
                "season",
                "week",
                "game_id",
                "player_id",
                "source_depth_observed_at",
                "source_depth_rank_pit",
                "source_depth_starter_pit",
            ]
        )
    selected = pd.concat(parts, ignore_index=True)
    selected["source_depth_starter_pit"] = (
        selected["source_depth_rank_pit"]
        .le(1)
        .astype(float)
        .where(selected["source_depth_rank_pit"].notna())
    )
    return selected[
        [
            "season",
            "week",
            "game_id",
            "player_id",
            "source_depth_observed_at",
            "source_depth_rank_pit",
            "source_depth_starter_pit",
        ]
    ]


def build_historical_source_features(
    panel: pd.DataFrame,
    *,
    snap_counts: pd.DataFrame | None = None,
    weekly_rosters: pd.DataFrame | None = None,
    participation: pd.DataFrame | None = None,
    pbp: pd.DataFrame | None = None,
    injuries: pd.DataFrame | None = None,
    depth_charts: pd.DataFrame | None = None,
    schedules: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach point-in-time historical source families to the frozen panel.

    Snap, participation and untimestamped depth-chart values are shifted one
    player-week. Same-week official injury evidence is allowed only when its
    modification timestamp precedes a schedule-derived prediction cutoff.
    """
    data = build_frozen_opportunity_features(panel)
    coverage_rows: list[dict[str, object]] = []

    def _counts(frame: pd.DataFrame | None, season_column: str = "season") -> dict[int, int]:
        if frame is None or frame.empty or season_column not in frame:
            return {}
        seasons = pd.to_numeric(frame[season_column], errors="coerce")
        return {
            int(season): int(count)
            for season, count in seasons.dropna().astype(int).value_counts().items()
        }

    def coverage(
        name: str,
        feature_columns: list[str],
        *,
        explicit: pd.Series | None = None,
        source_counts: dict[int, int] | None = None,
        id_counts: dict[int, tuple[int, int]] | None = None,
        statuses: dict[int, str] | None = None,
        required_files: dict[int, bool] | None = None,
    ) -> None:
        """Record distinct acquisition, match, feature and ID coverage."""
        source_counts = source_counts or {}
        id_counts = id_counts or {}
        statuses = statuses or {}
        required_files = required_files or {}
        explicit = (
            explicit.reindex(data.index, fill_value=False).astype(bool)
            if explicit is not None
            else pd.Series(False, index=data.index)
        )
        available_feature_columns = [column for column in feature_columns if column in data]
        feature_present = (
            data[available_feature_columns].notna().any(axis=1)
            if available_feature_columns
            else pd.Series(False, index=data.index)
        )
        audit = data[["season"]].assign(
            _explicit=explicit,
            _feature_present=feature_present,
        )
        for season, group in audit.groupby("season"):
            season = int(season)
            source_rows = source_counts.get(season, 0)
            id_source_rows, id_resolved_rows = id_counts.get(season, (0, 0))
            explicit_rows = int(group["_explicit"].sum())
            feature_rows = int(group["_feature_present"].sum())
            coverage_rows.append(
                {
                    "source_family": name,
                    "season": season,
                    "source_status": statuses.get(
                        season, "available" if source_rows else "source_file_unavailable"
                    ),
                    "source_file_available": bool(source_rows),
                    "required_files_available": required_files.get(season, bool(source_rows)),
                    "source_rows": source_rows,
                    "panel_rows": len(group),
                    "explicit_evidence_rows": explicit_rows,
                    "explicit_evidence_match_rate": float(group["_explicit"].mean()),
                    "post_imputation_feature_rows": feature_rows,
                    "post_imputation_feature_availability_rate": float(
                        group["_feature_present"].mean()
                    ),
                    "id_source_rows": id_source_rows,
                    "id_resolved_rows": id_resolved_rows,
                    "id_resolution_rate": (
                        float(id_resolved_rows / id_source_rows) if id_source_rows else np.nan
                    ),
                    # Backward-compatible aliases now explicitly mean evidence match.
                    "rows": len(group),
                    "matched_rows": explicit_rows,
                    "coverage_rate": float(group["_explicit"].mean()),
                }
            )

    snap_counts_by_season = _counts(snap_counts)
    snap_id_counts: dict[int, tuple[int, int]] = {}
    snap_statuses: dict[int, str] = {}
    snap_required: dict[int, bool] = {}
    if snap_counts is not None and weekly_rosters is not None and not snap_counts.empty:
        snaps = resolve_snap_player_ids(snap_counts, weekly_rosters)
        for season, group in snaps.groupby("season"):
            if pd.isna(season):
                continue
            snap_id_counts[int(season)] = (len(group), int(group["player_id"].notna().sum()))
            snap_statuses[int(season)] = "available"
            snap_required[int(season)] = True
        snaps = snaps.loc[snaps["player_id"].notna()].copy()
        snaps = _rolling_prior(snaps, "snap_share", "source_snap_share")
        snaps = _rolling_prior(snaps, "snap_count", "source_snap_count")
        snaps["source_snap_id_match_method_lag1"] = snaps.groupby("player_id", sort=False)[
            "id_match_method"
        ].shift(1)
        cols = [
            "season",
            "week",
            "player_id",
            "source_snap_share_lag1",
            "source_snap_share_roll3",
            "source_snap_share_trend",
            "source_snap_count_lag1",
            "source_snap_count_roll3",
            "source_snap_id_match_method_lag1",
        ]
        data = data.merge(
            snaps[cols].drop_duplicates(["season", "week", "player_id"], keep="last"),
            on=["season", "week", "player_id"],
            how="left",
            validate="many_to_one",
        )
    elif snap_counts is not None and not snap_counts.empty:
        for season in snap_counts_by_season:
            snap_statuses[season] = "missing_required_weekly_rosters"
            snap_required[season] = False
    coverage(
        "snap_counts",
        ["source_snap_share_lag1", "source_snap_count_lag1"],
        explicit=(
            data.get("source_snap_share_lag1", pd.Series(np.nan, index=data.index)).notna()
            | data.get("source_snap_count_lag1", pd.Series(np.nan, index=data.index)).notna()
        ),
        source_counts=snap_counts_by_season,
        id_counts=snap_id_counts,
        statuses=snap_statuses,
        required_files=snap_required,
    )

    participation_counts = _counts(participation)
    participation_id_counts: dict[int, tuple[int, int]] = {}
    participation_statuses: dict[int, str] = {}
    participation_required: dict[int, bool] = {}
    if participation is not None and pbp is not None and not participation.empty:
        pass_usage = aggregate_pass_play_participation(participation, pbp)
        # Participation files do not carry season/week columns themselves;
        # those are joined from PBP during aggregation.
        participation_counts = _counts(pass_usage)
        for season, group in pass_usage.groupby("season"):
            season = int(season)
            participation_id_counts[season] = (
                len(group),
                int(group["player_id"].notna().sum()),
            )
            participation_statuses[season] = "available"
            participation_required[season] = True
        pass_usage = _rolling_prior(
            pass_usage, "pass_play_participation_rate", "source_pass_participation"
        )
        cols = [
            "season",
            "week",
            "player_id",
            "source_pass_participation_lag1",
            "source_pass_participation_roll3",
            "source_pass_participation_trend",
        ]
        data = data.merge(
            pass_usage[cols].drop_duplicates(["season", "week", "player_id"], keep="last"),
            on=["season", "week", "player_id"],
            how="left",
            validate="many_to_one",
        )
    elif participation is not None and not participation.empty:
        for season in participation_counts:
            participation_statuses[season] = "missing_required_play_by_play"
            participation_required[season] = False
    pass_columns = [
        "source_pass_participation_lag1",
        "source_pass_participation_roll3",
        "source_pass_participation_trend",
    ]
    coverage(
        "pass_play_participation",
        pass_columns,
        explicit=(
            data[pass_columns].notna().any(axis=1)
            if set(pass_columns).issubset(data)
            else pd.Series(False, index=data.index)
        ),
        source_counts=participation_counts,
        id_counts=participation_id_counts,
        statuses=participation_statuses,
        required_files=participation_required,
    )

    depth_counts: dict[int, int] = {}
    depth_id_counts: dict[int, tuple[int, int]] = {}
    depth_statuses: dict[int, str] = {}
    depth_required: dict[int, bool] = {}
    depth_feature_columns: list[str] = []
    if depth_charts is not None and not depth_charts.empty:
        depth = canonicalize_depth_charts(depth_charts)
        depth_counts = _counts(depth)
        for season, group in depth.groupby("season"):
            if pd.isna(season):
                continue
            season = int(season)
            depth_id_counts[season] = (len(group), int(group["player_id"].notna().sum()))
        weekly = depth.loc[
            depth["schema_status"].eq("supported_weekly") & depth["player_id"].notna()
        ].copy()
        if not weekly.empty:
            weekly = (
                weekly.groupby(["season", "week", "player_id"], as_index=False)["depth_rank"]
                .min()
                .sort_values(["player_id", "season", "week"])
            )
            weekly = _rolling_prior(weekly, "depth_rank", "source_depth_rank")
            weekly["source_depth_starter_lag1"] = (
                weekly["source_depth_rank_lag1"]
                .le(1)
                .astype(float)
                .where(weekly["source_depth_rank_lag1"].notna())
            )
            weekly_columns = [
                "source_depth_rank_lag1",
                "source_depth_rank_roll3",
                "source_depth_starter_lag1",
            ]
            data = data.merge(
                weekly[["season", "week", "player_id", *weekly_columns]].drop_duplicates(
                    ["season", "week", "player_id"], keep="last"
                ),
                on=["season", "week", "player_id"],
                how="left",
                validate="many_to_one",
            )
            depth_feature_columns.extend(weekly_columns)
            for season in weekly["season"].dropna().astype(int).unique():
                depth_statuses[int(season)] = "available_weekly_shifted"
                depth_required[int(season)] = True

        timestamped = depth.loc[
            depth["schema_status"].eq("supported_timestamped") & depth["player_id"].notna()
        ].copy()
        if not timestamped.empty:
            timestamped = (
                timestamped.groupby(
                    ["season", "recent_team", "player_id", "observed_at"],
                    as_index=False,
                )["depth_rank"]
                .min()
                .sort_values("observed_at")
            )
            timestamped_seasons = set(timestamped["season"].dropna().astype(int))
            if schedules is None or schedules.empty:
                for season in timestamped_seasons:
                    depth_statuses[season] = "timestamped_schema_missing_schedule_cutoffs"
                    depth_required[season] = False
            else:
                cutoffs = _kickoff_cutoffs(schedules)
                point_in_time = _point_in_time_depth(data, timestamped, cutoffs)
                pit_columns = [
                    "source_depth_rank_pit",
                    "source_depth_starter_pit",
                    "source_depth_observed_at",
                ]
                data = data.merge(
                    point_in_time,
                    on=["season", "week", "game_id", "player_id"],
                    how="left",
                    validate="one_to_one",
                )
                depth_feature_columns.extend(pit_columns[:2])
                cutoff_game_ids = set(cutoffs.loc[cutoffs["prediction_cutoff"].notna(), "game_id"])
                panel_with_cutoff = data["game_id"].astype(str).isin(cutoff_game_ids)
                for season in timestamped_seasons:
                    season_cutoffs = panel_with_cutoff.loc[data["season"].astype(int).eq(season)]
                    if season_cutoffs.all():
                        depth_statuses[season] = "available_timestamped_point_in_time"
                        depth_required[season] = True
                    elif season_cutoffs.any():
                        depth_statuses[season] = "partial_game_cutoffs"
                        depth_required[season] = False
                    else:
                        depth_statuses[season] = "timestamped_schema_missing_game_cutoffs"
                        depth_required[season] = False
        unsupported = depth.loc[depth["schema_status"].eq("unsupported_schema")]
        for season in unsupported["season"].dropna().astype(int).unique():
            depth_statuses.setdefault(int(season), "unsupported_schema")
            depth_required.setdefault(int(season), False)
        legacy_rank = data.get("source_depth_rank_lag1", pd.Series(np.nan, index=data.index))
        timestamped_rank = data.get("source_depth_rank_pit", pd.Series(np.nan, index=data.index))
        legacy_starter = data.get("source_depth_starter_lag1", pd.Series(np.nan, index=data.index))
        timestamped_starter = data.get(
            "source_depth_starter_pit", pd.Series(np.nan, index=data.index)
        )
        data["source_depth_rank_pregame"] = legacy_rank.combine_first(timestamped_rank)
        data["source_depth_starter_pregame"] = legacy_starter.combine_first(timestamped_starter)
        depth_feature_columns.extend(["source_depth_rank_pregame", "source_depth_starter_pregame"])
    coverage(
        "depth_charts",
        depth_feature_columns,
        explicit=(
            data[depth_feature_columns].notna().any(axis=1)
            if depth_feature_columns
            else pd.Series(False, index=data.index)
        ),
        source_counts=depth_counts,
        id_counts=depth_id_counts,
        statuses=depth_statuses,
        required_files=depth_required,
    )

    injury_counts: dict[int, int] = {}
    injury_id_counts: dict[int, tuple[int, int]] = {}
    injury_statuses: dict[int, str] = {}
    injury_required: dict[int, bool] = {}
    if injuries is not None and schedules is not None and not injuries.empty:
        injury = canonicalize_injuries(injuries)
        injury_counts = _counts(injury)
        for season, group in injury.groupby("season"):
            if pd.isna(season):
                continue
            season = int(season)
            injury_id_counts[season] = (len(group), int(group["player_id"].notna().sum()))
        cutoffs = _kickoff_cutoffs(schedules)
        key_games = (
            data[["season", "week", "game_id", "recent_team", "player_id"]].drop_duplicates().copy()
        )
        key_games["game_id"] = key_games["game_id"].astype(str)
        key_games = key_games.merge(cutoffs, on="game_id", how="left")
        candidates = key_games.merge(
            injury,
            on=["season", "week", "recent_team", "player_id"],
            how="left",
            suffixes=("", "_injury"),
        )
        known = (
            candidates["date_modified"].notna()
            & candidates["prediction_cutoff"].notna()
            & candidates["date_modified"].le(candidates["prediction_cutoff"])
        )
        matched_injury = (
            candidates.loc[known]
            .sort_values("date_modified")
            .drop_duplicates(
                ["season", "week", "game_id", "recent_team", "player_id"],
                keep="last",
            )
        )
        injury_cols = [
            "season",
            "week",
            "game_id",
            "recent_team",
            "player_id",
            "official_report_availability_prior",
            "official_practice_availability_prior",
            "official_availability_prior",
            "official_injury_evidence_present",
            "report_status",
            "practice_status",
            "primary_injury",
            "date_modified",
            "prediction_cutoff",
        ]
        data = data.merge(
            matched_injury[injury_cols].rename(
                columns={
                    "date_modified": "official_evidence_date_modified",
                    "prediction_cutoff": "official_prediction_cutoff",
                }
            ),
            on=["season", "week", "game_id", "recent_team", "player_id"],
            how="left",
            validate="one_to_one",
        )
        available_seasons = set(injury_counts)
        timestamped_seasons = set(
            injury.loc[injury["date_modified"].notna(), "season"].dropna().astype(int)
        )
        game_ids_with_cutoff = set(
            cutoffs.loc[cutoffs["prediction_cutoff"].notna(), "game_id"].astype(str)
        )
        data["official_injury_source_available"] = (
            data["season"].astype(int).isin(timestamped_seasons)
            & data["game_id"].astype(str).isin(game_ids_with_cutoff)
        ).astype(int)
        known_absence = data["official_injury_source_available"].eq(1)
        data.loc[
            known_absence & data["official_injury_evidence_present"].isna(),
            "official_injury_evidence_present",
        ] = 0.0
        for season in available_seasons:
            season_rows = injury.loc[injury["season"].astype("Int64").eq(season)]
            panel_rows = data.loc[data["season"].astype(int).eq(season)]
            has_cutoff = panel_rows["game_id"].astype(str).isin(game_ids_with_cutoff)
            if season_rows["date_modified"].notna().sum() == 0:
                injury_statuses[season] = "source_timestamps_unavailable"
                injury_required[season] = False
            elif not has_cutoff.any():
                injury_statuses[season] = "missing_game_cutoffs"
                injury_required[season] = False
            elif not has_cutoff.all():
                injury_statuses[season] = "partial_game_cutoffs"
                injury_required[season] = False
            else:
                injury_statuses[season] = "available_point_in_time"
                injury_required[season] = True
    elif injuries is not None and not injuries.empty:
        injury = canonicalize_injuries(injuries)
        injury_counts = _counts(injury)
        for season, group in injury.groupby("season"):
            if pd.isna(season):
                continue
            season = int(season)
            injury_id_counts[season] = (len(group), int(group["player_id"].notna().sum()))
            injury_statuses[season] = "missing_required_schedule_cutoffs"
            injury_required[season] = False

    injury_feature_columns = [
        "official_report_availability_prior",
        "official_practice_availability_prior",
        "official_availability_prior",
    ]
    coverage(
        "official_injuries",
        [column for column in injury_feature_columns if column in data],
        explicit=(
            data.get(
                "official_injury_evidence_present",
                pd.Series(False, index=data.index),
            )
            .fillna(0)
            .eq(1)
        )
        if "official_injury_evidence_present" in data
        else pd.Series(False, index=data.index),
        source_counts=injury_counts,
        id_counts=injury_id_counts,
        statuses=injury_statuses,
        required_files=injury_required,
    )

    return data, pd.DataFrame(coverage_rows)


def run_historical_source_ablation(
    data: pd.DataFrame, coverage: pd.DataFrame
) -> HistoricalSourceAblationResult:
    base = [
        "position",
        "fantasy_points_ppr_q10",
        "fantasy_points_ppr_q50",
        "fantasy_points_ppr_q90",
    ]
    # Explicit pregame allowlist. Audit timestamps, source-status fields and ID
    # match methods are retained in artifacts but must never become predictors.
    families = {
        name: [column for column in columns if column in data]
        for name, columns in HISTORICAL_FEATURE_ALLOWLIST.items()
    }
    families = {name: cols for name, cols in families.items() if cols}
    objective = [
        c
        for name in ("snap_counts", "pass_participation", "depth_charts")
        for c in families.get(name, [])
    ]
    combined = [*objective, *families.get("official_availability", [])]
    variants: dict[str, tuple[pd.DataFrame, list[str]]] = {"numerical_baseline": (data, [])}
    variants.update({name: (data, cols) for name, cols in families.items()})
    if objective:
        variants["objective_sources_combined"] = (data, objective)
    if combined:
        variants["objective_plus_availability"] = (data, combined)
        shuffled = data.copy()
        rng = np.random.default_rng(42)
        for _, index in shuffled.groupby(
            ["season", "week", "position"], dropna=False
        ).groups.items():
            idx = np.asarray(list(index))
            if len(idx) > 1:
                perm = rng.permutation(idx)
                shuffled.loc[idx, combined] = shuffled.loc[perm, combined].to_numpy()
        shifted = data.sort_values(["player_id", "season", "week"]).copy()
        shifted[combined] = shifted.groupby("player_id", sort=False)[combined].shift(-1)
        variants["shuffled_player_control"] = (shuffled, combined)
        variants["shifted_time_leakage_control"] = (shifted, combined)

    predictions: list[pd.DataFrame] = []
    seasons = sorted(int(s) for s in data["season"].dropna().unique())
    for test_season in seasons[1:]:
        for method, (working, extra) in variants.items():
            train = working.loc[working["season"] < test_season].copy()
            test = working.loc[working["season"] == test_season].copy()
            out = test[
                KEYS
                + [
                    "actual_fantasy_points_ppr",
                    "fantasy_points_ppr_q10",
                    "fantasy_points_ppr_q50",
                    "fantasy_points_ppr_q90",
                ]
            ].copy()
            out["method"] = method
            out["test_season"] = test_season
            if not extra:
                shift = np.zeros(len(test))
            else:
                features = list(dict.fromkeys([*base, *extra]))
                model = _pipeline(train, features)
                residual = train["actual_fantasy_points_ppr"] - train["fantasy_points_ppr_q50"]
                model.fit(train[features], residual)
                raw = model.predict(test[features])
                half_width = (
                    (test["fantasy_points_ppr_q90"] - test["fantasy_points_ppr_q10"]) / 2.0
                ).clip(lower=1.0)
                shift = np.clip(raw, -0.30 * half_width, 0.30 * half_width)
            out["center_shift"] = shift
            for q in (10, 50, 90):
                out[f"adjusted_q{q}"] = np.maximum(
                    test[f"fantasy_points_ppr_q{q}"].to_numpy() + np.asarray(shift), 0.0
                )
            predictions.append(out)

    pred = pd.concat(predictions, ignore_index=True)
    summary = pd.DataFrame([_evaluate(group, method) for method, group in pred.groupby("method")])
    baseline = float(
        summary.loc[summary["method"].eq("numerical_baseline"), "mean_pinball"].iloc[0]
    )
    summary["pinball_improvement_vs_baseline_pct"] = (
        100 * (baseline - summary["mean_pinball"]) / baseline
    )
    summary = summary.sort_values("mean_pinball").reset_index(drop=True)

    season_rows = []
    position_rows = []
    for (method, season), group in pred.groupby(["method", "test_season"]):
        row = _evaluate(group, method)
        row["season"] = season
        season_rows.append(row)
    for (method, position), group in pred.groupby(["method", "position"]):
        row = _evaluate(group, method)
        row["position"] = position
        position_rows.append(row)

    manifest = pd.DataFrame(
        [
            {"ablation": name, "feature": feature}
            for name, (_, features) in variants.items()
            for feature in features
        ]
    )
    return HistoricalSourceAblationResult(
        pred,
        summary,
        pd.DataFrame(season_rows),
        pd.DataFrame(position_rows),
        manifest,
        coverage,
    )


def persist_historical_source_ablation(
    result: HistoricalSourceAblationResult, output_dir: str | Path
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frames = {
        "predictions": result.predictions,
        "summary": result.summary,
        "season_metrics": result.season_metrics,
        "position_metrics": result.position_metrics,
        "feature_manifest": result.feature_manifest,
        "source_coverage": result.coverage,
    }
    paths: dict[str, Path] = {}
    for name, frame in frames.items():
        path = output / f"historical_source_{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = path
    return paths


def _historical_calibration(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    actual_column = "actual_fantasy_points_ppr"
    for method, group in predictions.groupby("method"):
        actual = pd.to_numeric(group[actual_column], errors="coerce")
        for quantile in (10, 50, 90):
            prediction = pd.to_numeric(group[f"adjusted_q{quantile}"], errors="coerce")
            valid = actual.notna() & prediction.notna()
            rows.append(
                {
                    "method": method,
                    "metric": f"q{quantile}_empirical_rate",
                    "nominal_rate": quantile / 100,
                    "observed_rate": float((actual[valid] <= prediction[valid]).mean()),
                    "rows": int(valid.sum()),
                }
            )
        valid_interval = (
            actual.notna() & group["adjusted_q10"].notna() & group["adjusted_q90"].notna()
        )
        interval_actual = actual[valid_interval]
        rows.append(
            {
                "method": method,
                "metric": "q10_q90_interval_coverage",
                "nominal_rate": 0.8,
                "observed_rate": float(
                    (
                        (interval_actual >= group.loc[valid_interval, "adjusted_q10"])
                        & (interval_actual <= group.loc[valid_interval, "adjusted_q90"])
                    ).mean()
                ),
                "rows": int(valid_interval.sum()),
            }
        )
    return pd.DataFrame(rows)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def persist_historical_source_experiment(
    result: HistoricalSourceAblationResult,
    output_dir: str | Path,
    *,
    config: dict[str, Any],
    git_commit: str,
    decision: str = "reject",
) -> dict[str, Path]:
    """Persist the complete material-experiment contract required by AGENTS.md."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    calibration = _historical_calibration(result.predictions)
    scored = result.predictions.copy()
    scored["q50_error"] = pd.to_numeric(scored["adjusted_q50"], errors="coerce") - pd.to_numeric(
        scored["actual_fantasy_points_ppr"], errors="coerce"
    )

    def add_bias(metrics: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
        bias = scored.groupby(group_columns, as_index=False)["q50_error"].agg(
            q50_bias="mean", q50_error_std="std"
        )
        return metrics.merge(bias, on=group_columns, how="left", validate="one_to_one")

    summary_metrics = add_bias(result.summary, ["method"])
    season_metrics = add_bias(result.season_metrics, ["method", "season"])
    position_metrics = add_bias(result.position_metrics, ["method", "position"])
    residual_cohorts = (
        scored.groupby(["method", "season", "position"], as_index=False)
        .agg(
            rows=("q50_error", "size"),
            q50_bias=("q50_error", "mean"),
            q50_mae=("q50_error", lambda values: float(values.abs().mean())),
            q50_error_std=("q50_error", "std"),
        )
        .sort_values(["method", "q50_mae"], ascending=[True, False])
    )
    frames = {
        "predictions.parquet": result.predictions,
        "summary_metrics.csv": summary_metrics,
        "season_metrics.csv": season_metrics,
        "position_metrics.csv": position_metrics,
        "calibration.csv": calibration,
        "feature_manifest.csv": result.feature_manifest,
        "source_coverage.csv": result.coverage,
        "residual_cohorts.csv": residual_cohorts,
    }
    paths: dict[str, Path] = {}
    for filename, frame in frames.items():
        path = output / filename
        if path.suffix == ".parquet":
            frame.to_parquet(path, index=False)
        else:
            frame.to_csv(path, index=False)
        paths[path.stem] = path

    config_path = output / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    paths["config"] = config_path
    commit_path = output / "git_commit.txt"
    commit_path.write_text(f"{git_commit.strip()}\n", encoding="utf-8")
    paths["git_commit"] = commit_path

    baseline = summary_metrics.loc[summary_metrics["method"].eq("numerical_baseline")].iloc[0]
    deployable = summary_metrics.loc[
        ~summary_metrics["method"].isin(
            ["numerical_baseline", "shuffled_player_control", "shifted_time_leakage_control"]
        )
    ].sort_values("mean_pinball")
    best = deployable.iloc[0] if not deployable.empty else baseline
    controls = summary_metrics.loc[
        summary_metrics["method"].isin(["shuffled_player_control", "shifted_time_leakage_control"])
    ]
    unavailable = result.coverage.loc[
        ~result.coverage["required_files_available"].astype(bool),
        ["source_family", "season", "source_status"],
    ]
    largest_bias = residual_cohorts.loc[residual_cohorts["method"].eq(best["method"])].sort_values(
        "q50_bias", key=lambda values: values.abs(), ascending=False
    )
    notes = [
        "# Historical source ablation",
        "",
        "## Source coverage and cutoff validity",
        "",
        "Coverage is reported before predictive metrics. File availability, explicit "
        "pre-cutoff evidence matches, post-domain-imputation feature availability, "
        "and player-ID resolution are separate fields in `source_coverage.csv`.",
        "",
        unavailable.to_markdown(index=False)
        if not unavailable.empty
        else "All required sources were usable.",
        "",
        "## Preregistered protocol",
        "",
        f"- Hypothesis: {config.get('hypothesis', 'Objective historical sources improve the frozen numerical engine.')}",
        f"- Train/test windows: {config.get('train_test_windows', 'Expanding-window; each test season trained only on earlier seasons.')}",
        f"- Cutoff: {config.get('cutoff', 'Per-game kickoff minus 1.5 hours, UTC-normalized.')}",
        f"- Feature families: {config.get('feature_families', list(HISTORICAL_FEATURE_ALLOWLIST))}",
        f"- Baseline: {config.get('baseline', 'Frozen numerical quantile engine.')}",
        f"- Primary metric: {config.get('primary_metric', 'Mean pinball loss.')}",
        "",
        "## Results and calibration",
        "",
        (
            f"- Baseline mean pinball: {float(baseline['mean_pinball']):.6f}; "
            f"q50 MAE: {float(baseline['mae']):.6f}; "
            f"q10-q90 coverage: {float(baseline['interval_coverage']):.6f}; "
            f"width: {float(baseline['interval_width']):.6f}."
        ),
        (
            f"- Best eligible challenger: {best['method']}; mean pinball "
            f"{float(best['mean_pinball']):.6f}; improvement versus baseline "
            f"{float(best['pinball_improvement_vs_baseline_pct']):.3f}%."
        ),
        f"- Baseline q50 bias (prediction minus actual): {float(baseline['q50_bias']):.6f}.",
        (
            f"- Largest absolute q50-bias cohort for the best eligible challenger: "
            f"{int(largest_bias.iloc[0]['season'])} {largest_bias.iloc[0]['position']}, "
            f"bias {float(largest_bias.iloc[0]['q50_bias']):.6f}, q50 MAE "
            f"{float(largest_bias.iloc[0]['q50_mae']):.6f}."
            if not largest_bias.empty
            else "- No residual cohort was available."
        ),
        "- Full q10, q50, q90 empirical rates and interval coverage are in `calibration.csv`.",
        "- Held-out season and eligible-position results are in `season_metrics.csv` "
        "and `position_metrics.csv`.",
        "- Season-position bias and q50 MAE cohorts are in `residual_cohorts.csv`.",
        "",
        "## Negative controls",
        "",
        controls[
            [
                "method",
                "mean_pinball",
                "pinball_improvement_vs_baseline_pct",
                "interval_coverage",
            ]
        ].to_markdown(index=False),
        "",
        "## Failure analysis",
        "",
        "- Missing evidence remains missing; it is not reported as healthy or zero usage.",
        "- Unsupported or untimestamped source seasons fail closed and remain visible in coverage.",
        "- A present injury file without usable timestamps remains unavailable/NaN for "
        "modeling with a 0 explicit-evidence match rate.",
        "- Audit timestamps and ID match methods are retained for review but excluded from the predictor allowlist.",
        "- A gain from incomplete coverage or failed controls is not promotable.",
        "",
        "## Decision",
        "",
        f"**{decision.upper()}**. No family is promoted by this experiment.",
        "",
    ]
    notes_path = output / "notes.md"
    notes_path.write_text("\n".join(notes), encoding="utf-8")
    paths["notes"] = notes_path

    artifact_entries = []
    for path in sorted(output.iterdir()):
        if path.name == "manifest.json" or not path.is_file():
            continue
        artifact_entries.append(
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": _file_sha256(path),
            }
        )
    manifest = {
        "experiment_id": config.get("experiment_id", output.name),
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit.strip(),
        "decision": decision,
        "coverage_reported_before_metrics": True,
        "artifacts": artifact_entries,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    paths["manifest"] = manifest_path
    return paths
