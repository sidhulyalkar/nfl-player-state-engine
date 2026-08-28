from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from player_state_engine.config import FeatureConfig
from player_state_engine.features.opportunity import (
    OPPORTUNITY_TARGETS,
    add_opportunity_history_features,
    add_roster_transition_features,
)

SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}

BASE_STATS = (
    "passing_attempts",
    "completions",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "targets",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "receiving_air_yards",
    "receiving_yards_after_catch",
    "target_share",
    "air_yards_share",
    "snap_count",
    "route_count",
    "fantasy_points",
    "fantasy_points_ppr",
)

DEFAULT_TARGETS = (
    "fantasy_points_ppr",
    "targets",
    "carries",
    "receptions",
    "receiving_yards",
    "rushing_yards",
    "passing_yards",
)

IDENTIFIER_COLUMNS = {
    "player_id",
    "player_name",
    "game_id",
    "gameday",
    "is_projection_row",
    "fold_week",
}

CURRENT_OUTCOME_COLUMNS = (
    set(BASE_STATS)
    | set(OPPORTUNITY_TARGETS)
    | {"attempts", "carries_inside_10", "targets_inside_10"}
)

_SCHEDULE_CONTEXT_DEFAULTS: dict[str, object] = {
    "is_home": 0,
    "spread_line": np.nan,
    "total_line": np.nan,
    "team_rest": np.nan,
    "opponent_rest": np.nan,
    "roof": "unknown",
    "surface": "unknown",
    "temp": np.nan,
    "wind": np.nan,
}


def _ensure_schedule_context_defaults(frame: pd.DataFrame) -> pd.DataFrame:
    """Guarantee optional schedule context exists whether or not the source publishes it."""

    data = frame.copy()
    for column, default in _SCHEDULE_CONTEXT_DEFAULTS.items():
        if column not in data.columns:
            data[column] = default
    return data


def _first_present(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    return next((name for name in candidates if name in frame.columns), None)


def calculate_fantasy_points_ppr(frame: pd.DataFrame) -> pd.Series:
    def col(name: str) -> pd.Series:
        if name not in frame.columns:
            return pd.Series(0.0, index=frame.index, dtype=float)
        return pd.to_numeric(frame[name], errors="coerce").fillna(0.0)

    return (
        col("passing_yards") / 25.0
        + 4.0 * col("passing_tds")
        - 2.0 * col("interceptions")
        + col("rushing_yards") / 10.0
        + 6.0 * col("rushing_tds")
        + col("receiving_yards") / 10.0
        + 6.0 * col("receiving_tds")
        + col("receptions")
    )


def canonicalize_player_stats(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    aliases = {
        "player_display_name": "player_name",
        "opponent": "opponent_team",
        "opponent_abbr": "opponent_team",
        "passing_interceptions": "interceptions",
    }
    for old, new in aliases.items():
        if old in data.columns and new not in data.columns:
            data = data.rename(columns={old: new})

    if "player_id" not in data.columns:
        source = _first_present(data, ("gsis_id", "player_gsis_id", "nfl_id"))
        if source is None:
            raise ValueError("Player stats require player_id or gsis_id.")
        data["player_id"] = data[source].astype(str)

    if "player_name" not in data.columns:
        source = _first_present(data, ("full_name", "display_name", "player_id"))
        data["player_name"] = data[source].astype(str) if source else data["player_id"].astype(str)

    if "recent_team" not in data.columns:
        source = _first_present(data, ("team", "posteam", "club_code"))
        if source is None:
            raise ValueError("Player stats require recent_team or team.")
        data["recent_team"] = data[source]

    if "position" not in data.columns:
        source = _first_present(data, ("position_group", "pos"))
        data["position"] = data[source] if source else "UNK"

    required = ("season", "week")
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise ValueError(f"Player stats missing required columns: {missing}")

    if "passing_attempts" not in data.columns and "attempts" in data.columns:
        data["passing_attempts"] = data["attempts"]

    for optional_column in ("snap_count", "route_count", "carries_inside_10", "targets_inside_10"):
        data[f"{optional_column}_available"] = int(optional_column in data.columns)
    for column in BASE_STATS:
        if column not in data.columns:
            data[column] = 0.0
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)
    for optional_column in ("carries_inside_10", "targets_inside_10"):
        if optional_column not in data.columns:
            data[optional_column] = np.nan
        else:
            data[optional_column] = pd.to_numeric(data[optional_column], errors="coerce")

    if "fantasy_points_ppr" not in frame.columns:
        data["fantasy_points_ppr"] = calculate_fantasy_points_ppr(data)
    if "fantasy_points" not in frame.columns:
        data["fantasy_points"] = data["fantasy_points_ppr"] - data["receptions"]

    data["season"] = pd.to_numeric(data["season"], errors="raise").astype(int)
    data["week"] = pd.to_numeric(data["week"], errors="raise").astype(int)
    data["player_id"] = data["player_id"].astype(str)
    data["recent_team"] = data["recent_team"].astype(str)
    data["position"] = data["position"].fillna("UNK").astype(str).str.upper()
    if "is_projection_row" not in data.columns:
        data["is_projection_row"] = False
    data["is_projection_row"] = data["is_projection_row"].fillna(False).astype(bool)
    data["week_index"] = data["season"] * 25 + data["week"]

    if "game_id" not in data.columns:
        opponent = data.get("opponent_team", "UNK")
        data["game_id"] = (
            data["season"].astype(str)
            + "_"
            + data["week"].astype(str).str.zfill(2)
            + "_"
            + data["recent_team"].astype(str)
            + "_"
            + pd.Series(opponent, index=data.index).astype(str)
        )
    return data


def schedule_to_team_rows(schedules: pd.DataFrame) -> pd.DataFrame:
    required = {"season", "week", "away_team", "home_team"}
    missing = required - set(schedules.columns)
    if missing:
        raise ValueError(f"Schedules missing required columns: {sorted(missing)}")

    schedule = schedules.copy()
    if "game_id" not in schedule.columns:
        schedule["game_id"] = (
            schedule["season"].astype(str)
            + "_"
            + schedule["week"].astype(str).str.zfill(2)
            + "_"
            + schedule["away_team"].astype(str)
            + "_"
            + schedule["home_team"].astype(str)
        )

    shared = [
        column
        for column in (
            "game_id",
            "season",
            "week",
            "gameday",
            "game_type",
            "spread_line",
            "total_line",
            "roof",
            "surface",
            "temp",
            "wind",
        )
        if column in schedule.columns
    ]

    home = schedule[shared + ["home_team", "away_team"]].copy()
    home = home.rename(columns={"home_team": "recent_team", "away_team": "schedule_opponent"})
    home["is_home"] = 1
    home["team_rest"] = schedule.get("home_rest", np.nan)
    home["opponent_rest"] = schedule.get("away_rest", np.nan)

    away = schedule[shared + ["away_team", "home_team"]].copy()
    away = away.rename(columns={"away_team": "recent_team", "home_team": "schedule_opponent"})
    away["is_home"] = 0
    away["team_rest"] = schedule.get("away_rest", np.nan)
    away["opponent_rest"] = schedule.get("home_rest", np.nan)

    long = pd.concat([home, away], ignore_index=True)
    long["season"] = long["season"].astype(int)
    long["week"] = long["week"].astype(int)
    return long


def merge_schedule_context(stats: pd.DataFrame, schedules: pd.DataFrame | None) -> pd.DataFrame:
    if schedules is None or schedules.empty:
        return _ensure_schedule_context_defaults(stats)

    team_schedule = schedule_to_team_rows(schedules)
    existing_schedule_columns = {
        "game_id",
        "gameday",
        "is_home",
        "spread_line",
        "total_line",
        "team_rest",
        "opponent_rest",
        "roof",
        "surface",
        "temp",
        "wind",
        "schedule_opponent",
    }
    data = stats.drop(
        columns=[c for c in existing_schedule_columns if c in stats.columns], errors="ignore"
    )
    merged = data.merge(
        team_schedule, on=["season", "week", "recent_team"], how="left", validate="many_to_one"
    )
    if "opponent_team" not in merged.columns:
        merged["opponent_team"] = merged["schedule_opponent"]
    else:
        merged["opponent_team"] = (
            merged["opponent_team"].replace({"": np.nan}).fillna(merged["schedule_opponent"])
        )
    merged = merged.drop(columns=["schedule_opponent"], errors="ignore")
    return _ensure_schedule_context_defaults(merged)


def _shifted_rolling(series: pd.Series, window: int, statistic: str) -> pd.Series:
    shifted = series.shift(1)
    rolling = shifted.rolling(window=window, min_periods=1)
    if statistic == "mean":
        return rolling.mean()
    if statistic == "std":
        return rolling.std(ddof=0)
    raise ValueError(statistic)


def _add_player_history_features(data: pd.DataFrame, config: FeatureConfig) -> pd.DataFrame:
    """Create shifted player histories with one grouping pass per statistic.

    The original scaffold used ``groupby.transform(lambda ...)`` for every
    statistic/window pair. That is correct but painfully slow on six real NFL
    seasons. Grouped rolling/ewm operations preserve the same point-in-time
    semantics while making recurring refreshes practical.
    """

    data = data.sort_values(["player_id", "season", "week", "game_id"]).copy()
    player_ids = data["player_id"]
    grouped = data.groupby("player_id", sort=False, group_keys=False)
    generated: dict[str, pd.Series] = {
        "player_history_count": grouped.cumcount(),
        "season_transition": grouped["season"].diff().fillna(0).ne(0).astype(int),
        "weeks_since_last_game": grouped["week_index"].diff().fillna(1).clip(lower=1, upper=30),
    }

    history_stats = [column for column in BASE_STATS if column in data.columns]
    for column in history_stats:
        shifted = grouped[column].shift(1)
        generated[f"{column}_lag1"] = shifted
        shifted_grouped = shifted.groupby(player_ids, sort=False)
        for window in config.rolling_windows:
            generated[f"{column}_roll{window}_mean"] = (
                shifted_grouped.rolling(window=window, min_periods=1)
                .mean()
                .reset_index(level=0, drop=True)
                .reindex(data.index)
            )
            generated[f"{column}_roll{window}_std"] = (
                shifted_grouped.rolling(window=window, min_periods=1)
                .std(ddof=0)
                .reset_index(level=0, drop=True)
                .reindex(data.index)
            )
        for halflife in config.ewm_halflives:
            generated[f"{column}_ewm_h{halflife}"] = (
                shifted_grouped.ewm(halflife=halflife, adjust=False, min_periods=1)
                .mean()
                .reset_index(level=0, drop=True)
                .reindex(data.index)
            )
    return pd.concat([data, pd.DataFrame(generated, index=data.index)], axis=1)


def _add_position_priors(data: pd.DataFrame, metrics: Iterable[str]) -> pd.DataFrame:
    keys = ["season", "week", "week_index", "position"]
    actual = data.loc[~data["is_projection_row"]].copy()
    weekly = actual.groupby(keys, as_index=False)[list(metrics)].mean()
    weekly = weekly.sort_values(["position", "week_index"])
    for metric in metrics:
        weekly[f"position_{metric}_prior4"] = weekly.groupby("position", sort=False)[
            metric
        ].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
    keep = keys[:2] + ["position"] + [c for c in weekly.columns if c.startswith("position_")]
    return data.merge(
        weekly[keep], on=["season", "week", "position"], how="left", validate="many_to_one"
    )


def _add_team_context(data: pd.DataFrame, metrics: Iterable[str]) -> pd.DataFrame:
    metrics = [m for m in metrics if m in data.columns]
    actual = data.loc[(~data["is_projection_row"]) & data["position"].isin(SKILL_POSITIONS)].copy()
    if actual.empty or not metrics:
        return data

    offense = actual.groupby(["season", "week", "week_index", "recent_team"], as_index=False)[
        metrics
    ].sum()
    offense = offense.sort_values(["recent_team", "week_index"])
    for metric in metrics:
        offense[f"team_{metric}_roll4"] = offense.groupby("recent_team", sort=False)[
            metric
        ].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
    offense_keep = ["season", "week", "recent_team"] + [
        c for c in offense.columns if c.startswith("team_")
    ]
    result = data.merge(
        offense[offense_keep],
        on=["season", "week", "recent_team"],
        how="left",
        validate="many_to_one",
    )

    if "opponent_team" in actual.columns:
        defense = (
            actual.dropna(subset=["opponent_team"])
            .groupby(["season", "week", "week_index", "opponent_team"], as_index=False)[metrics]
            .sum()
        )
        defense = defense.sort_values(["opponent_team", "week_index"])
        for metric in metrics:
            defense[f"opp_allowed_{metric}_roll4"] = defense.groupby("opponent_team", sort=False)[
                metric
            ].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
        defense_keep = ["season", "week", "opponent_team"] + [
            c for c in defense.columns if c.startswith("opp_allowed_")
        ]
        result = result.merge(
            defense[defense_keep],
            on=["season", "week", "opponent_team"],
            how="left",
            validate="many_to_one",
        )
    return result


def build_weekly_features(
    player_stats: pd.DataFrame,
    schedules: pd.DataFrame | None = None,
    config: FeatureConfig | None = None,
) -> pd.DataFrame:
    """Create leakage-safe weekly player features.

    Every statistic-derived feature uses shift(1) before rolling or exponential
    aggregation. Schedule information is treated as known pregame context.
    """

    config = config or FeatureConfig()
    data = canonicalize_player_stats(player_stats)
    data = merge_schedule_context(data, schedules)
    data = _add_player_history_features(data, config)
    data = add_opportunity_history_features(data, windows=config.rolling_windows)
    data = add_roster_transition_features(data)
    prior_metrics = (
        "fantasy_points_ppr",
        "targets",
        "carries",
        "receiving_yards",
        "rushing_yards",
        "passing_yards",
    )
    data = _add_position_priors(data, prior_metrics)
    data = _add_team_context(data, prior_metrics)

    data["rest_advantage"] = pd.to_numeric(data.get("team_rest"), errors="coerce") - pd.to_numeric(
        data.get("opponent_rest"), errors="coerce"
    )
    data["is_dome"] = (
        data["roof"].astype(str).str.lower().isin({"dome", "closed"}).astype(int)
    )
    data["is_grass"] = (
        data["surface"].astype(str).str.lower().str.contains("grass").astype(int)
    )
    data["week_sin"] = np.sin(2 * np.pi * data["week"] / 18.0)
    data["week_cos"] = np.cos(2 * np.pi * data["week"] / 18.0)
    return data.sort_values(["season", "week", "game_id", "recent_team", "player_id"]).reset_index(
        drop=True
    )


SAFE_PREGAME_CONTEXT_COLUMNS = {
    "season",
    "week",
    "recent_team",
    "opponent_team",
    "position",
    "is_home",
    "spread_line",
    "total_line",
    "team_rest",
    "opponent_rest",
    "roof",
    "surface",
    "temp",
    "wind",
    "rest_advantage",
    "is_dome",
    "is_grass",
    "week_sin",
    "week_cos",
    "player_history_count",
    "season_transition",
    "weeks_since_last_game",
    "is_rookie_prior",
    "team_changed_prior",
    "quarterback_changed_prior",
    "previous_primary_qb",
    "ol_continuity",
    "ol_continuity_missing",
    "snap_count_available",
    "route_count_available",
    "carries_inside_10_available",
    "targets_inside_10_available",
}


def _is_generated_pregame_feature(column: str) -> bool:
    return (
        column.endswith("_lag1")
        or "_roll" in column
        or "_ewm_h" in column
        or column.startswith("position_")
        or column.startswith("team_")
        or column.startswith("opp_allowed_")
        or column.startswith("availability_")
        or column.startswith("news_")
        or column.startswith("persona_")
        or (
            column.startswith("opportunity_")
            and ("_lag" in column or "_roll" in column or "_ewm" in column)
        )
    )


def feature_columns(frame: pd.DataFrame, targets: Iterable[str] = DEFAULT_TARGETS) -> list[str]:
    """Return an explicit pregame feature allowlist.

    Raw nflverse weekly tables contain many same-game outcomes beyond the named
    targets (EPA, first downs, success rates, fantasy variants, and more). A
    generic "all columns except target" selector therefore leaks the game being
    predicted. Only schedule context, generated lagged/history features, and
    point-in-time intelligence snapshots are admitted here.
    """

    target_set = set(targets)
    columns: list[str] = []
    for column in frame.columns:
        if (
            column in target_set
            or column in IDENTIFIER_COLUMNS
            or column in CURRENT_OUTCOME_COLUMNS
        ):
            continue
        if column not in SAFE_PREGAME_CONTEXT_COLUMNS and not _is_generated_pregame_feature(column):
            continue
        series = frame[column]
        if not series.notna().any():
            continue
        dtype = series.dtype
        if (
            pd.api.types.is_numeric_dtype(dtype)
            or pd.api.types.is_bool_dtype(dtype)
            or pd.api.types.is_object_dtype(dtype)
        ):
            columns.append(column)
    return columns


TARGET_DRIVER_STATS: dict[str, tuple[str, ...]] = {
    "fantasy_points_ppr": (
        "fantasy_points_ppr",
        "passing_attempts",
        "completions",
        "passing_yards",
        "passing_tds",
        "interceptions",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "targets",
        "receptions",
        "receiving_yards",
        "receiving_tds",
        "receiving_air_yards",
        "receiving_yards_after_catch",
        "target_share",
        "air_yards_share",
    ),
    "targets": (
        "targets",
        "receptions",
        "receiving_air_yards",
        "target_share",
        "air_yards_share",
        "snap_count",
        "route_count",
    ),
    "carries": ("carries", "rushing_yards", "rushing_tds", "snap_count"),
    "receptions": (
        "targets",
        "receptions",
        "receiving_yards",
        "target_share",
        "route_count",
        "snap_count",
    ),
    "receiving_yards": (
        "targets",
        "receptions",
        "receiving_yards",
        "receiving_tds",
        "receiving_air_yards",
        "receiving_yards_after_catch",
        "target_share",
        "air_yards_share",
        "route_count",
    ),
    "rushing_yards": ("carries", "rushing_yards", "rushing_tds", "snap_count"),
    "passing_yards": (
        "passing_attempts",
        "completions",
        "passing_yards",
        "passing_tds",
        "interceptions",
    ),
}


def feature_columns_for_target(frame: pd.DataFrame, target: str) -> list[str]:
    """Select a compact, auditable feature family for one target.

    This reduces compute and makes ablations interpretable without allowing raw
    same-week nflverse outcomes into the model.
    """
    safe = feature_columns(frame, targets=(target,))
    drivers = TARGET_DRIVER_STATS.get(target, (target,))
    common = SAFE_PREGAME_CONTEXT_COLUMNS
    selected: list[str] = []
    for column in safe:
        if (
            column in common
            or column.startswith(("availability_", "news_", "persona_"))
            or (column.startswith("opportunity_") and ("_lag" in column or "_roll" in column))
        ):
            selected.append(column)
            continue
        prefixes = tuple(
            prefix
            for stat in drivers
            for prefix in (f"{stat}_", f"position_{stat}_", f"team_{stat}_", f"opp_allowed_{stat}_")
        )
        if column.startswith(prefixes):
            selected.append(column)
    return selected


def build_prediction_slate(
    historical_stats: pd.DataFrame,
    schedules: pd.DataFrame,
    season: int,
    week: int,
    config: FeatureConfig | None = None,
) -> pd.DataFrame:
    config = config or FeatureConfig()
    history = canonicalize_player_stats(historical_stats)
    cutoff = season * 25 + week
    history = history.loc[history["week_index"] < cutoff].copy()
    if history.empty:
        raise ValueError("No historical rows exist before the requested prediction week.")

    target_schedule = schedule_to_team_rows(schedules)
    target_schedule = target_schedule.loc[
        (target_schedule["season"] == season) & (target_schedule["week"] == week)
    ]
    if target_schedule.empty:
        raise ValueError(f"No schedule rows found for season={season}, week={week}.")

    playing_teams = set(target_schedule["recent_team"].astype(str))
    latest = (
        history.sort_values(["week_index", "game_id"]).groupby("player_id", as_index=False).tail(1)
    )
    same_season_recent = (latest["season"] == season) & (
        (week - latest["week"]) <= config.active_lookback_weeks
    )
    prior_season_bridge = (latest["season"] == season - 1) & (week <= 2)
    latest = latest.loc[
        (same_season_recent | prior_season_bridge) & latest["recent_team"].isin(playing_teams)
    ].copy()
    if latest.empty:
        raise ValueError("No active players could be inferred for the requested slate.")

    schedule_context = target_schedule.set_index("recent_team")
    slate_rows: list[dict[str, object]] = []
    for _, player in latest.iterrows():
        team = str(player["recent_team"])
        context = schedule_context.loc[team]
        row: dict[str, object] = {
            "season": season,
            "week": week,
            "game_id": context["game_id"],
            "player_id": player["player_id"],
            "player_name": player["player_name"],
            "recent_team": team,
            "opponent_team": context["schedule_opponent"],
            "position": player["position"],
            "is_projection_row": True,
        }
        for stat in BASE_STATS:
            row[stat] = 0.0
        slate_rows.append(row)

    combined = pd.concat([history, pd.DataFrame(slate_rows)], ignore_index=True, sort=False)
    featured = build_weekly_features(combined, schedules=schedules, config=config)
    return featured.loc[featured["is_projection_row"]].reset_index(drop=True)
