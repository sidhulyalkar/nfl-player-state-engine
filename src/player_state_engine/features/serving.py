from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from player_state_engine.config import FeatureConfig
from player_state_engine.features.weekly import (
    BASE_STATS,
    SKILL_POSITIONS,
    build_weekly_features,
    canonicalize_player_stats,
    merge_schedule_context,
    schedule_to_team_rows,
)

# nflverse roster status semantics. We keep statuses that still represent an NFL contract
# because injured/reserve/suspended players remain legitimate fantasy assets. Practice-squad
# and released/free-agent rows are not part of the production draft player pool.
_INCLUDED_ROSTER_STATUSES = {
    "ACT",
    "E14",
    "EXE",
    "INA",
    "PUP",
    "RES",
    "RSN",
    "SUS",
}
_EXCLUDED_ROSTER_STATUSES = {
    "CUT",
    "DEV",
    "NWT",
    "RET",
    "RFA",
    "RSR",
    "TRC",
    "TRD",
    "TRL",
    "TRT",
    "UFA",
}
_PRIOR_METRICS = (
    "fantasy_points_ppr",
    "targets",
    "carries",
    "receiving_yards",
    "rushing_yards",
    "passing_yards",
)


@dataclass(frozen=True, slots=True)
class PredictionSlateDiagnostics:
    season: int
    week: int
    eligible_roster_rows: int
    contracted_roster_rows: int
    resolved_roster_rows: int
    unresolved_identity_rows: int
    excluded_roster_status_rows: int
    unknown_roster_status_rows: int
    ambiguous_team_identity_rows: int
    veteran_rows: int
    rookie_or_no_history_rows: int
    team_change_rows: int
    projection_rows: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _RosterNormalizationDiagnostics:
    eligible_rows: int
    contracted_rows: int
    resolved_rows: int
    unresolved_identity_rows: int
    excluded_status_rows: int
    unknown_status_rows: int
    ambiguous_team_identity_rows: int


def _first_present(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    return next((column for column in candidates if column in frame.columns), None)


def _canonicalize_current_rosters(
    rosters: pd.DataFrame,
    *,
    season: int,
    playing_teams: set[str],
) -> tuple[pd.DataFrame, _RosterNormalizationDiagnostics]:
    """Normalize a current nflverse-style roster snapshot without name-based joins."""

    data = rosters.copy()
    if "season" in data:
        season_values = pd.to_numeric(data["season"], errors="coerce")
        data = data.loc[season_values.eq(season)].copy()

    team_column = _first_present(data, ("recent_team", "team", "club_code"))
    position_column = _first_present(data, ("position", "pos", "position_group"))
    id_column = _first_present(data, ("gsis_id", "player_id", "player_gsis_id"))
    name_column = _first_present(data, ("player_name", "full_name", "display_name"))
    status_column = _first_present(data, ("status", "roster_status", "status_description_abbr"))
    if team_column is None or position_column is None:
        raise ValueError("Current rosters require team and position columns.")
    if id_column is None:
        raise ValueError("Current rosters require gsis_id/player_id; name matching is not allowed.")
    if status_column is None:
        raise ValueError("Current rosters require an explicit roster status column.")

    data["recent_team"] = data[team_column].astype("string").str.upper().str.strip()
    data["position"] = data[position_column].astype("string").str.upper().str.strip()
    data["player_id"] = data[id_column].astype("string").str.strip()
    data["roster_status"] = data[status_column].astype("string").str.upper().str.strip()
    if name_column is None:
        data["player_name"] = data["player_id"]
    else:
        data["player_name"] = data[name_column].astype("string").fillna(data["player_id"])

    data = data.loc[
        data["position"].isin(SKILL_POSITIONS) & data["recent_team"].isin(playing_teams)
    ].copy()
    eligible_rows = int(len(data))

    status = data["roster_status"]
    unknown_status = ~status.isin(_INCLUDED_ROSTER_STATUSES | _EXCLUDED_ROSTER_STATUSES)
    unknown_status_rows = int(unknown_status.sum())
    excluded_status = status.isin(_EXCLUDED_ROSTER_STATUSES)
    excluded_status_rows = int(excluded_status.sum())
    data = data.loc[status.isin(_INCLUDED_ROSTER_STATUSES)].copy()
    contracted_rows = int(len(data))

    unresolved = (
        data["player_id"].isna()
        | data["player_id"].eq("")
        | data["player_id"].eq("<NA>")
        | data["player_id"].str.lower().eq("nan")
    )
    unresolved_identity_rows = int(unresolved.sum())
    data = data.loc[~unresolved].copy()

    # Weekly/appended roster snapshots can contain the same player repeatedly. Resolve them only
    # when an actual temporal ordering field exists. If there is no temporal key and the same
    # GSIS identity appears on multiple teams, dropping duplicates would invent a current team.
    temporal_columns = [
        column for column in ("week", "dt", "date_modified") if column in data.columns
    ]
    ambiguous_ids: set[str] = set()
    if not temporal_columns and data["player_id"].duplicated(keep=False).any():
        for player_id, group in data.groupby("player_id", sort=False):
            if group["recent_team"].nunique(dropna=True) > 1:
                ambiguous_ids.add(str(player_id))
    ambiguous_team_identity_rows = len(ambiguous_ids)
    if ambiguous_ids:
        data = data.loc[~data["player_id"].astype(str).isin(ambiguous_ids)].copy()

    if temporal_columns:
        sort_columns: list[str] = []
        for column in temporal_columns:
            helper = f"__sort_{column}"
            if column == "week":
                data[helper] = pd.to_numeric(data[column], errors="coerce")
            else:
                data[helper] = pd.to_datetime(data[column], utc=True, errors="coerce")
            sort_columns.append(helper)
        data = data.sort_values(sort_columns, kind="stable")
        data = data.drop(columns=sort_columns)
    else:
        data = data.sort_values(["recent_team", "position", "player_name"], kind="stable")
    data = data.drop_duplicates("player_id", keep="last")

    diagnostics = _RosterNormalizationDiagnostics(
        eligible_rows=eligible_rows,
        contracted_rows=contracted_rows,
        resolved_rows=int(len(data)),
        unresolved_identity_rows=unresolved_identity_rows,
        excluded_status_rows=excluded_status_rows,
        unknown_status_rows=unknown_status_rows,
        ambiguous_team_identity_rows=ambiguous_team_identity_rows,
    )
    return data.reset_index(drop=True), diagnostics


def _latest_prior_values(
    history: pd.DataFrame,
    targets: pd.DataFrame,
    *,
    group_column: str,
    value_columns: list[str],
) -> pd.DataFrame:
    """Return latest strictly-prior aggregate values for arbitrary future rows."""

    result = pd.DataFrame(index=targets.index, columns=value_columns, dtype=float)
    if history.empty or targets.empty:
        return result

    for group_name, target_group in targets.groupby(group_column, dropna=False):
        history_group = history.loc[history[group_column].eq(group_name)].sort_values("week_index")
        if history_group.empty:
            continue
        weeks = history_group["week_index"].to_numpy(dtype=int)
        query = target_group["week_index"].to_numpy(dtype=int)
        locations = np.searchsorted(weeks, query, side="left") - 1
        valid = locations >= 0
        if not valid.any():
            continue
        for column in value_columns:
            values = pd.to_numeric(history_group[column], errors="coerce").to_numpy(dtype=float)
            selected = np.full(len(target_group), np.nan, dtype=float)
            selected[valid] = values[locations[valid]]
            result.loc[target_group.index, column] = selected
    return result


def _fill_projection_qb_context(slate: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """Carry forward prior-QB context with the same strictly-prior semantics as training."""

    data = slate.copy()
    if data.empty:
        return data
    qb = history.loc[history["position"].eq("QB")].copy()
    if qb.empty:
        return data
    qb["_volume"] = pd.to_numeric(qb.get("passing_attempts", 0.0), errors="coerce").fillna(0.0)
    primary = qb.sort_values(
        ["week_index", "recent_team", "_volume"],
        ascending=[True, True, False],
        kind="stable",
    ).drop_duplicates(["week_index", "recent_team"], keep="first")

    if "previous_primary_qb" not in data:
        data["previous_primary_qb"] = pd.NA
    if "quarterback_changed_prior" not in data:
        data["quarterback_changed_prior"] = 0

    for team, indexes in data.groupby("recent_team", sort=False).groups.items():
        target_week = int(data.loc[list(indexes), "week_index"].min())
        prior = primary.loc[
            primary["recent_team"].eq(team) & primary["week_index"].lt(target_week)
        ].sort_values("week_index")
        if prior.empty:
            continue
        last = str(prior.iloc[-1]["player_id"])
        changed = 0
        if len(prior) >= 2:
            changed = int(str(prior.iloc[-2]["player_id"]) != last)
        data.loc[list(indexes), "previous_primary_qb"] = last
        data.loc[list(indexes), "quarterback_changed_prior"] = changed
    return data


def _fill_projection_aggregate_context(
    slate: pd.DataFrame,
    historical_stats: pd.DataFrame,
    schedules: pd.DataFrame,
) -> pd.DataFrame:
    """Restore aggregate context that exact-week training joins cannot serve into the future."""

    if slate.empty:
        return slate
    data = slate.copy()
    history = merge_schedule_context(canonicalize_player_stats(historical_stats), schedules)
    history = history.loc[history["week_index"] < data["week_index"].min()].copy()
    if history.empty:
        return data

    metrics = [metric for metric in _PRIOR_METRICS if metric in history.columns]

    position_weekly = (
        history.groupby(["week_index", "position"], as_index=False)[metrics]
        .mean()
        .sort_values(["position", "week_index"])
    )
    position_columns: list[str] = []
    for metric in metrics:
        column = f"position_{metric}_prior4"
        position_weekly[column] = position_weekly.groupby("position", sort=False)[metric].transform(
            lambda values: values.rolling(4, min_periods=1).mean()
        )
        position_columns.append(column)
    position_prior = _latest_prior_values(
        position_weekly,
        data,
        group_column="position",
        value_columns=position_columns,
    )
    for column in position_columns:
        if column not in data:
            data[column] = np.nan
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(position_prior[column])

    skill_history = history.loc[history["position"].isin(SKILL_POSITIONS)].copy()
    offense = (
        skill_history.groupby(["week_index", "recent_team"], as_index=False)[metrics]
        .sum()
        .sort_values(["recent_team", "week_index"])
    )
    team_columns: list[str] = []
    for metric in metrics:
        column = f"team_{metric}_roll4"
        offense[column] = offense.groupby("recent_team", sort=False)[metric].transform(
            lambda values: values.rolling(4, min_periods=1).mean()
        )
        team_columns.append(column)
    team_prior = _latest_prior_values(
        offense,
        data,
        group_column="recent_team",
        value_columns=team_columns,
    )
    for column in team_columns:
        if column not in data:
            data[column] = np.nan
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(team_prior[column])

    defense_history = skill_history.dropna(subset=["opponent_team"])
    if not defense_history.empty:
        defense = (
            defense_history.groupby(["week_index", "opponent_team"], as_index=False)[metrics]
            .sum()
            .sort_values(["opponent_team", "week_index"])
        )
        opponent_columns: list[str] = []
        for metric in metrics:
            column = f"opp_allowed_{metric}_roll4"
            defense[column] = defense.groupby("opponent_team", sort=False)[metric].transform(
                lambda values: values.rolling(4, min_periods=1).mean()
            )
            opponent_columns.append(column)
        opponent_prior = _latest_prior_values(
            defense,
            data,
            group_column="opponent_team",
            value_columns=opponent_columns,
        )
        for column in opponent_columns:
            if column not in data:
                data[column] = np.nan
            data[column] = pd.to_numeric(data[column], errors="coerce").fillna(
                opponent_prior[column]
            )

    return _fill_projection_qb_context(data, history)


def build_current_roster_prediction_slate(
    historical_stats: pd.DataFrame,
    schedules: pd.DataFrame,
    current_rosters: pd.DataFrame,
    *,
    season: int,
    week: int,
    config: FeatureConfig | None = None,
    fail_on_unresolved_identity: bool = True,
    fail_on_unknown_status: bool = True,
    fail_on_ambiguous_team_identity: bool = True,
) -> tuple[pd.DataFrame, PredictionSlateDiagnostics]:
    """Build a future slate from current roster truth rather than prior-season team inference.

    Veterans inherit shifted history through stable GSIS IDs. Traded players receive their
    current team and therefore expose ``team_changed_prior=1``. Rookies/no-history players remain
    explicit zero-history rows. No player is joined to historical outcomes by name.
    """

    config = config or FeatureConfig()
    history = canonicalize_player_stats(historical_stats)
    cutoff = season * 25 + week
    history = history.loc[history["week_index"] < cutoff].copy()
    if history.empty:
        raise ValueError("No historical rows exist before the requested prediction week.")

    target_schedule = schedule_to_team_rows(schedules)
    target_schedule = target_schedule.loc[
        (target_schedule["season"] == season) & (target_schedule["week"] == week)
    ].copy()
    if target_schedule.empty:
        raise ValueError(f"No schedule rows found for season={season}, week={week}.")

    playing_teams = set(target_schedule["recent_team"].astype(str))
    roster, roster_diagnostics = _canonicalize_current_rosters(
        current_rosters,
        season=season,
        playing_teams=playing_teams,
    )
    if fail_on_unresolved_identity and roster_diagnostics.unresolved_identity_rows:
        raise ValueError(
            "Current roster snapshot contains contracted skill-position rows without GSIS IDs; "
            f"count={roster_diagnostics.unresolved_identity_rows}."
        )
    if fail_on_unknown_status and roster_diagnostics.unknown_status_rows:
        raise ValueError(
            "Current roster snapshot contains unknown roster statuses; "
            f"count={roster_diagnostics.unknown_status_rows}. Update status semantics explicitly."
        )
    if fail_on_ambiguous_team_identity and roster_diagnostics.ambiguous_team_identity_rows:
        raise ValueError(
            "Current roster snapshot contains cross-team duplicate GSIS identities without a "
            "temporal ordering key; "
            f"count={roster_diagnostics.ambiguous_team_identity_rows}."
        )
    if roster.empty:
        raise ValueError("No current contracted skill-position roster rows matched this slate.")

    schedule_context = target_schedule.set_index("recent_team")
    slate_rows: list[dict[str, object]] = []
    for _, player in roster.iterrows():
        team = str(player["recent_team"])
        context = schedule_context.loc[team]
        row: dict[str, object] = {
            "season": season,
            "week": week,
            "game_id": context["game_id"],
            "player_id": str(player["player_id"]),
            "player_name": str(player["player_name"]),
            "recent_team": team,
            "opponent_team": context["schedule_opponent"],
            "position": str(player["position"]),
            "roster_status": str(player["roster_status"]),
            "is_projection_row": True,
        }
        for stat in BASE_STATS:
            row[stat] = 0.0
        slate_rows.append(row)

    projection_rows = pd.DataFrame(slate_rows)
    combined = pd.concat([history, projection_rows], ignore_index=True, sort=False)
    featured = build_weekly_features(combined, schedules=schedules, config=config)
    slate = featured.loc[featured["is_projection_row"]].reset_index(drop=True)
    slate = _fill_projection_aggregate_context(slate, history, schedules)

    historical_ids = set(history["player_id"].astype(str))
    veteran = slate["player_id"].astype(str).isin(historical_ids)
    team_changes = pd.to_numeric(
        slate.get("team_changed_prior", pd.Series(0, index=slate.index)), errors="coerce"
    ).fillna(0).gt(0)
    diagnostics = PredictionSlateDiagnostics(
        season=int(season),
        week=int(week),
        eligible_roster_rows=roster_diagnostics.eligible_rows,
        contracted_roster_rows=roster_diagnostics.contracted_rows,
        resolved_roster_rows=roster_diagnostics.resolved_rows,
        unresolved_identity_rows=roster_diagnostics.unresolved_identity_rows,
        excluded_roster_status_rows=roster_diagnostics.excluded_status_rows,
        unknown_roster_status_rows=roster_diagnostics.unknown_status_rows,
        ambiguous_team_identity_rows=roster_diagnostics.ambiguous_team_identity_rows,
        veteran_rows=int(veteran.sum()),
        rookie_or_no_history_rows=int((~veteran).sum()),
        team_change_rows=int(team_changes.sum()),
        projection_rows=int(len(slate)),
    )
    return slate, diagnostics
