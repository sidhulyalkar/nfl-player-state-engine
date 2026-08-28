from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from player_state_engine.features.weekly import SKILL_POSITIONS, canonicalize_player_stats

PRESEASON_TARGETS = (
    "fantasy_points_ppr",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "rushing_yards",
    "rushing_tds",
    "receptions",
    "receiving_yards",
    "receiving_tds",
)

# Historical opening-week rosters contain several contract states that still represent a
# fantasy asset. Practice-squad/free-agent/released states are not part of the ordinary draft
# pool. Unknown states fail closed so upstream schema changes cannot silently redefine training.
_INCLUDED_STATUSES = {"ACT", "E14", "EXE", "INA", "PUP", "RES", "RSN", "SUS"}
_EXCLUDED_STATUSES = {"CUT", "DEV", "NWT", "RET", "RFA", "RSR", "TRC", "TRD", "TRL", "TRT", "UFA"}


@dataclass(frozen=True, slots=True)
class PreseasonDatasetDiagnostics:
    seasons: tuple[int, ...]
    snapshot_week: int
    rows: int
    zero_outcome_rows: int
    rookie_rows: int
    no_prior_season_rows: int
    unresolved_identity_rows: int
    excluded_status_rows: int
    unknown_status_rows: int
    ambiguous_identity_rows: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _RosterDiagnostics:
    unresolved_identity_rows: int = 0
    excluded_status_rows: int = 0
    unknown_status_rows: int = 0
    ambiguous_identity_rows: int = 0


def _first_present(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def _normalize_opening_roster(
    rosters: pd.DataFrame,
    *,
    season: int,
    snapshot_week: int | None,
    fail_on_unknown_status: bool = True,
) -> tuple[pd.DataFrame, _RosterDiagnostics]:
    data = rosters.copy()
    if "season" not in data:
        raise ValueError("Roster data requires season.")
    season_values = pd.to_numeric(data["season"], errors="coerce")
    data = data.loc[season_values.eq(int(season))].copy()
    if snapshot_week is not None:
        if "week" not in data:
            raise ValueError("Historical opening rosters require week.")
        weeks = pd.to_numeric(data["week"], errors="coerce")
        data = data.loc[weeks.eq(int(snapshot_week))].copy()
    if data.empty:
        raise ValueError(
            f"No roster rows found for season={season}"
            + ("" if snapshot_week is None else f", week={snapshot_week}")
        )

    id_column = _first_present(data, ("gsis_id", "player_id", "player_gsis_id"))
    team_column = _first_present(data, ("team", "recent_team", "club_code"))
    position_column = _first_present(data, ("position", "pos", "position_group"))
    name_column = _first_present(data, ("full_name", "player_name", "display_name"))
    status_column = _first_present(data, ("status", "roster_status", "status_description_abbr"))
    if id_column is None or team_column is None or position_column is None:
        raise ValueError("Roster data requires GSIS/player ID, team, and position columns.")
    if status_column is None:
        raise ValueError("Roster data requires an explicit roster status column.")

    data["player_id"] = data[id_column].astype("string").str.strip()
    data["recent_team"] = data[team_column].astype("string").str.upper().str.strip()
    data["position"] = data[position_column].astype("string").str.upper().str.strip()
    data["roster_status"] = data[status_column].astype("string").str.upper().str.strip()
    data["player_name"] = (
        data[name_column].astype("string").fillna(data["player_id"])
        if name_column is not None
        else data["player_id"]
    )
    data = data.loc[data["position"].isin(SKILL_POSITIONS)].copy()

    status = data["roster_status"]
    unknown_status = ~status.isin(_INCLUDED_STATUSES | _EXCLUDED_STATUSES)
    unknown_status_rows = int(unknown_status.sum())
    if fail_on_unknown_status and unknown_status_rows:
        examples = sorted(status.loc[unknown_status].dropna().astype(str).unique())[:5]
        raise ValueError(f"Unknown roster statuses for season {season}: {examples}")
    excluded = status.isin(_EXCLUDED_STATUSES) | unknown_status
    excluded_status_rows = int(excluded.sum())
    data = data.loc[status.isin(_INCLUDED_STATUSES)].copy()

    unresolved = (
        data["player_id"].isna()
        | data["player_id"].eq("")
        | data["player_id"].eq("<NA>")
        | data["player_id"].str.lower().eq("nan")
    )
    unresolved_identity_rows = int(unresolved.sum())
    data = data.loc[~unresolved].copy()

    temporal_columns = [
        column for column in ("week", "dt", "date_modified") if column in data.columns
    ]
    if temporal_columns:
        helper_columns: list[str] = []
        for column in temporal_columns:
            helper = f"__sort_{column}"
            data[helper] = (
                pd.to_numeric(data[column], errors="coerce")
                if column == "week"
                else pd.to_datetime(data[column], utc=True, errors="coerce")
            )
            helper_columns.append(helper)
        data = data.sort_values(helper_columns, kind="stable").drop(columns=helper_columns)

    ambiguous_ids = []
    for player_id, group in data.groupby("player_id", sort=False):
        if group["recent_team"].nunique(dropna=True) > 1 and not temporal_columns:
            ambiguous_ids.append(str(player_id))
    if ambiguous_ids:
        data = data.loc[~data["player_id"].astype(str).isin(ambiguous_ids)].copy()

    data = data.drop_duplicates("player_id", keep="last")
    data["season"] = int(season)
    return (
        data[
            ["season", "player_id", "player_name", "recent_team", "position", "roster_status"]
        ].reset_index(drop=True),
        _RosterDiagnostics(
            unresolved_identity_rows=unresolved_identity_rows,
            excluded_status_rows=excluded_status_rows,
            unknown_status_rows=unknown_status_rows,
            ambiguous_identity_rows=len(ambiguous_ids),
        ),
    )


def _season_outcomes(player_stats: pd.DataFrame) -> pd.DataFrame:
    stats = player_stats.copy()
    if "season_type" in stats:
        stats = stats.loc[stats["season_type"].astype(str).str.upper().eq("REG")].copy()
    data = canonicalize_player_stats(stats)
    data = data.loc[data["position"].isin(SKILL_POSITIONS)].copy()

    # These scoring components are present in nflverse weekly player stats but are not all part
    # of BASE_STATS in the weekly feature builder. Missing historical columns remain explicit
    # zero outcomes rather than disappearing from the season target table.
    for column in PRESEASON_TARGETS:
        if column not in data:
            data[column] = 0.0
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)

    group_columns = ["season", "player_id"]
    totals = data.groupby(group_columns, as_index=False)[list(PRESEASON_TARGETS)].sum()
    games = (
        data.groupby(group_columns)["game_id"].nunique().rename("games_with_stat_row").reset_index()
    )
    latest = (
        data.sort_values(["season", "week", "game_id"], kind="stable")
        .groupby(group_columns, as_index=False)
        .tail(1)[["season", "player_id", "recent_team", "player_name", "position"]]
        .rename(columns={"recent_team": "season_end_team"})
    )
    return totals.merge(games, on=group_columns, validate="one_to_one").merge(
        latest, on=group_columns, how="left", validate="one_to_one"
    )


def _player_metadata(players: pd.DataFrame | None) -> pd.DataFrame:
    if players is None or players.empty:
        return pd.DataFrame(columns=["player_id"])
    data = players.copy()
    id_column = _first_present(data, ("gsis_id", "player_id", "player_gsis_id"))
    if id_column is None:
        raise ValueError("Player metadata requires gsis_id/player_id.")
    data["player_id"] = data[id_column].astype("string").str.strip()
    output = pd.DataFrame({"player_id": data["player_id"]})
    aliases = {
        "birth_date": ("birth_date", "birthdate", "date_of_birth"),
        "draft_year": ("draft_year",),
        "draft_round": ("draft_round",),
        "draft_pick": ("draft_pick", "draft_ovr"),
    }
    for target, names in aliases.items():
        source = _first_present(data, names)
        output[target] = data[source] if source is not None else np.nan
    output = output.loc[output["player_id"].notna() & output["player_id"].ne("")].copy()
    return output.drop_duplicates("player_id", keep="last")


def _attach_static_features(frame: pd.DataFrame, players: pd.DataFrame | None) -> pd.DataFrame:
    out = frame.merge(_player_metadata(players), on="player_id", how="left", validate="many_to_one")
    for column in ("draft_year", "draft_round", "draft_pick"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    birth = pd.to_datetime(out["birth_date"], errors="coerce")
    season_start = pd.to_datetime(out["season"].astype(int).astype(str) + "-09-01")
    out["age_at_season_start"] = (season_start - birth).dt.days / 365.2425
    out["rookie"] = out["draft_year"].eq(out["season"]).fillna(False).astype(int)
    return out


def _attach_exact_prior_seasons(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    base_columns = ["season", "player_id", "recent_team", "games_with_stat_row", *PRESEASON_TARGETS]
    for lag in (1, 2):
        prior = out[base_columns].copy()
        prior["season"] = prior["season"] + lag
        prior = prior.rename(
            columns={
                "recent_team": f"prior{lag}_opening_team",
                "games_with_stat_row": f"prior{lag}_games",
                **{target: f"prior{lag}_{target}" for target in PRESEASON_TARGETS},
            }
        )
        out = out.merge(prior, on=["season", "player_id"], how="left", validate="one_to_one")
        out[f"prior{lag}_rostered"] = out[f"prior{lag}_opening_team"].notna().astype(int)

    out["team_changed_from_prior"] = (
        out["prior1_opening_team"].notna()
        & out["recent_team"].ne(out["prior1_opening_team"])
    ).astype(int)
    out = out.sort_values(["player_id", "season"], kind="stable")
    out["experience_seasons_prior"] = out.groupby("player_id", sort=False).cumcount()
    return out


def _attach_roster_competition(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["team_position_roster_count"] = out.groupby(
        ["season", "recent_team", "position"], dropna=False
    )["player_id"].transform("size")
    skill_count = out.groupby(["season", "recent_team"], dropna=False)["player_id"].transform("size")
    out["team_skill_roster_count"] = skill_count
    return out


def preseason_feature_columns(frame: pd.DataFrame) -> list[str]:
    """Return the frozen season-start feature family, excluding target-season outcomes."""

    preferred = [
        "position",
        "recent_team",
        "roster_status",
        "age_at_season_start",
        "draft_year",
        "draft_round",
        "draft_pick",
        "rookie",
        "experience_seasons_prior",
        "team_changed_from_prior",
        "team_position_roster_count",
        "team_skill_roster_count",
        "prior1_rostered",
        "prior2_rostered",
        "prior1_games",
        "prior2_games",
    ]
    for lag in (1, 2):
        preferred.extend(f"prior{lag}_{target}" for target in PRESEASON_TARGETS)
    return [column for column in preferred if column in frame]


def build_preseason_season_dataset(
    player_stats: pd.DataFrame,
    weekly_rosters: pd.DataFrame,
    *,
    players: pd.DataFrame | None = None,
    seasons: Iterable[int] | None = None,
    snapshot_week: int = 1,
    fail_on_unknown_status: bool = True,
) -> tuple[pd.DataFrame, PreseasonDatasetDiagnostics]:
    """Build one season-start row per rostered fantasy asset with zero-output seasons retained.

    The candidate universe is the opening-week roster snapshot. Same-season outcomes are joined
    afterward and missing box-score seasons are filled with zero. Predictors use only static
    metadata, roster structure, and exact prior-season aggregates.
    """

    available_seasons = sorted(
        int(value)
        for value in pd.to_numeric(weekly_rosters.get("season"), errors="coerce").dropna().unique()
    )
    requested = tuple(sorted(set(int(season) for season in (seasons or available_seasons))))
    if not requested:
        raise ValueError("No seasons requested for preseason dataset.")

    roster_frames: list[pd.DataFrame] = []
    unresolved = excluded = unknown = ambiguous = 0
    for season in requested:
        roster, diagnostics = _normalize_opening_roster(
            weekly_rosters,
            season=season,
            snapshot_week=snapshot_week,
            fail_on_unknown_status=fail_on_unknown_status,
        )
        roster_frames.append(roster)
        unresolved += diagnostics.unresolved_identity_rows
        excluded += diagnostics.excluded_status_rows
        unknown += diagnostics.unknown_status_rows
        ambiguous += diagnostics.ambiguous_identity_rows
    universe = pd.concat(roster_frames, ignore_index=True)
    if universe.duplicated(["season", "player_id"]).any():
        raise ValueError("Opening roster universe contains duplicate season/player identities.")

    outcomes = _season_outcomes(player_stats)
    data = universe.merge(
        outcomes.drop(columns=["season_end_team", "player_name", "position"], errors="ignore"),
        on=["season", "player_id"],
        how="left",
        validate="one_to_one",
    )
    for target in PRESEASON_TARGETS:
        data[target] = pd.to_numeric(data[target], errors="coerce").fillna(0.0)
    data["games_with_stat_row"] = pd.to_numeric(
        data["games_with_stat_row"], errors="coerce"
    ).fillna(0).astype(int)
    data["zero_season_outcome"] = data["fantasy_points_ppr"].eq(0.0).astype(int)

    data = _attach_static_features(data, players)
    data = _attach_exact_prior_seasons(data)
    data = _attach_roster_competition(data)
    data = data.sort_values(["season", "position", "recent_team", "player_id"]).reset_index(drop=True)

    diagnostics = PreseasonDatasetDiagnostics(
        seasons=requested,
        snapshot_week=int(snapshot_week),
        rows=int(len(data)),
        zero_outcome_rows=int(data["zero_season_outcome"].sum()),
        rookie_rows=int(data["rookie"].sum()),
        no_prior_season_rows=int(data["prior1_rostered"].eq(0).sum()),
        unresolved_identity_rows=int(unresolved),
        excluded_status_rows=int(excluded),
        unknown_status_rows=int(unknown),
        ambiguous_identity_rows=int(ambiguous),
    )
    return data, diagnostics


def build_current_preseason_features(
    historical_dataset: pd.DataFrame,
    current_rosters: pd.DataFrame,
    *,
    season: int,
    players: pd.DataFrame | None = None,
    fail_on_unknown_status: bool = True,
) -> pd.DataFrame:
    """Create a target-season feature frame using a current roster snapshot and frozen history."""

    current, diagnostics = _normalize_opening_roster(
        current_rosters,
        season=season,
        snapshot_week=None,
        fail_on_unknown_status=fail_on_unknown_status,
    )
    if diagnostics.unresolved_identity_rows or diagnostics.ambiguous_identity_rows:
        raise ValueError(
            "Current preseason roster identity is incomplete or ambiguous; refusing production serving."
        )

    history = historical_dataset.copy()
    missing_targets = [target for target in PRESEASON_TARGETS if target not in history]
    if missing_targets:
        raise ValueError(f"Historical preseason dataset missing targets: {missing_targets}")

    current = _attach_static_features(current, players)
    current["games_with_stat_row"] = 0
    for target in PRESEASON_TARGETS:
        current[target] = np.nan

    # Build exact lag joins from historical season rows only. Current target outcomes remain absent.
    lag_source = history[
        ["season", "player_id", "recent_team", "games_with_stat_row", *PRESEASON_TARGETS]
    ].copy()
    for lag in (1, 2):
        prior = lag_source.copy()
        prior["season"] = prior["season"] + lag
        prior = prior.rename(
            columns={
                "recent_team": f"prior{lag}_opening_team",
                "games_with_stat_row": f"prior{lag}_games",
                **{target: f"prior{lag}_{target}" for target in PRESEASON_TARGETS},
            }
        )
        current = current.merge(prior, on=["season", "player_id"], how="left", validate="one_to_one")
        current[f"prior{lag}_rostered"] = current[f"prior{lag}_opening_team"].notna().astype(int)
    current["team_changed_from_prior"] = (
        current["prior1_opening_team"].notna()
        & current["recent_team"].ne(current["prior1_opening_team"])
    ).astype(int)

    experience = history.groupby("player_id")["season"].nunique()
    current["experience_seasons_prior"] = current["player_id"].map(experience).fillna(0).astype(int)
    current = _attach_roster_competition(current)
    return current.sort_values(["position", "recent_team", "player_id"]).reset_index(drop=True)
