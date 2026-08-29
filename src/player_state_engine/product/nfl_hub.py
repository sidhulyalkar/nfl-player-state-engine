from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from player_state_engine.data.io import read_table
from player_state_engine.product.provenance import frame_records

HUB_SCHEMA_VERSION = 1
HUB_AUTHORITY = "observational_nfl_state_only"


def _to_pandas(frame: object) -> pd.DataFrame:
    if isinstance(frame, pd.DataFrame):
        return frame.copy()
    if hasattr(frame, "to_pandas"):
        return frame.to_pandas()  # type: ignore[no-any-return]
    raise TypeError(f"Unsupported dataframe type: {type(frame)!r}")


def _first_present(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def _clean_text(series: pd.Series, *, upper: bool = False) -> pd.Series:
    out = series.astype("string").str.strip()
    out = out.mask(out.str.lower().isin({"", "nan", "none", "<na>"}))
    return out.str.upper() if upper else out


def _normalize_external_id(value: object) -> str | None:
    """Normalize representation-only numeric ID drift without altering opaque identifiers."""

    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return None
    if "." in text:
        whole, _, fractional = text.partition(".")
        if whole.lstrip("+-").isdigit() and fractional and set(fractional) == {"0"}:
            return whole
    return text


def _normalize_external_ids(series: pd.Series) -> pd.Series:
    return series.map(_normalize_external_id).astype("string")


def _numeric(frame: pd.DataFrame, names: Iterable[str]) -> pd.Series:
    column = _first_present(frame, names)
    if column is None:
        return pd.Series(float("nan"), index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _text(frame: pd.DataFrame, names: Iterable[str], *, upper: bool = False) -> pd.Series:
    column = _first_present(frame, names)
    if column is None:
        return pd.Series(pd.NA, index=frame.index, dtype="string")
    return _clean_text(frame[column], upper=upper)


def _latest_per_player(frame: pd.DataFrame, *, source_name: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    data = frame.copy()
    temporal = _first_present(
        data,
        (
            "dt",  # nflverse depth-chart point-in-time timestamp from 2025 onward
            "date_modified",
            "last_transaction_date",
            "status_date",
            "report_date",
            "gameday",
            "game_date",
            "updated_at",
        ),
    )
    if temporal is not None:
        data["__hub_time"] = pd.to_datetime(data[temporal], errors="coerce", utc=True)
        data = data.sort_values(
            ["player_id", "__hub_time"],
            kind="mergesort",
            na_position="first",
        )
        return data.drop_duplicates("player_id", keep="last").drop(columns=["__hub_time"])
    duplicates = data["player_id"].astype(str).duplicated(keep=False)
    if duplicates.any():
        examples = sorted(data.loc[duplicates, "player_id"].astype(str).unique())[:5]
        raise ValueError(
            f"{source_name} contains ambiguous duplicate player identities without a temporal field: {examples}"
        )
    return data


def canonicalize_rosters(rosters: pd.DataFrame, *, season: int) -> pd.DataFrame:
    """Return one current roster row per GSIS identity without inferring model health state."""

    data = rosters.copy()
    if "season" in data:
        data = data.loc[pd.to_numeric(data["season"], errors="coerce").eq(int(season))].copy()
    if data.empty:
        raise ValueError(f"No roster rows available for season {season}.")
    id_column = _first_present(data, ("gsis_id", "player_id", "player_gsis_id"))
    if id_column is None:
        raise ValueError("Roster source requires GSIS/player identity.")
    data["player_id"] = _clean_text(data[id_column])
    data["team"] = _text(data, ("team", "recent_team", "club_code"), upper=True)
    data["position"] = _text(data, ("position", "pos", "position_group"), upper=True)
    data["player_name"] = _text(data, ("full_name", "player_name", "display_name"))
    data["player_name"] = data["player_name"].fillna(data["player_id"])

    status = pd.Series(pd.NA, index=data.index, dtype="string")
    provenance = pd.Series(pd.NA, index=data.index, dtype="string")
    for column in (
        "status_short_description",
        "status_description_abbr",
        "roster_status",
        "status",
    ):
        if column not in data:
            continue
        values = _clean_text(data[column])
        fill = status.isna() & values.notna()
        status.loc[fill] = values.loc[fill]
        provenance.loc[fill] = column + ":" + values.loc[fill]
    data["roster_status"] = status
    data["roster_status_provenance"] = provenance

    data = data.loc[data["player_id"].notna()].copy()
    data = _latest_per_player(data, source_name="rosters")
    return data[
        [
            "player_id",
            "player_name",
            "team",
            "position",
            "roster_status",
            "roster_status_provenance",
        ]
    ].reset_index(drop=True)


def canonicalize_depth_charts(depth_charts: pd.DataFrame, *, season: int) -> pd.DataFrame:
    if depth_charts.empty:
        return pd.DataFrame(columns=["player_id", "depth_rank", "depth_position", "depth_team"])
    data = depth_charts.copy()
    if "season" in data:
        data = data.loc[pd.to_numeric(data["season"], errors="coerce").eq(int(season))].copy()
    id_column = _first_present(data, ("gsis_id", "player_id", "player_gsis_id"))
    if id_column is None or data.empty:
        return pd.DataFrame(columns=["player_id", "depth_rank", "depth_position", "depth_team"])
    data["player_id"] = _clean_text(data[id_column])
    data["depth_rank"] = _numeric(
        data,
        ("pos_rank", "depth_team", "depth_chart_order", "depth_rank", "rank"),
    )
    data["depth_position"] = _text(
        data,
        ("pos_abb", "position", "depth_position", "position_group"),
        upper=True,
    )
    data["depth_team"] = _text(data, ("team", "club_code", "recent_team"), upper=True)
    data = data.loc[data["player_id"].notna()].copy()
    data = _latest_per_player(data, source_name="depth_charts")
    return data[["player_id", "depth_rank", "depth_position", "depth_team"]].reset_index(drop=True)


def canonicalize_injuries(injuries: pd.DataFrame, *, season: int) -> pd.DataFrame:
    if injuries.empty:
        return pd.DataFrame(
            columns=["player_id", "injury_status", "practice_status", "primary_injury"]
        )
    data = injuries.copy()
    if "season" in data:
        data = data.loc[pd.to_numeric(data["season"], errors="coerce").eq(int(season))].copy()
    id_column = _first_present(data, ("gsis_id", "player_id", "player_gsis_id"))
    if id_column is None or data.empty:
        return pd.DataFrame(
            columns=["player_id", "injury_status", "practice_status", "primary_injury"]
        )
    data["player_id"] = _clean_text(data[id_column])
    data["injury_status"] = _text(
        data,
        ("report_status", "game_status", "injury_status", "status"),
    )
    data["practice_status"] = _text(
        data,
        ("practice_status", "practice_status_description", "practice_participation"),
    )
    data["primary_injury"] = _text(
        data,
        ("report_primary_injury", "primary_injury", "injury"),
    )
    data = data.loc[data["player_id"].notna()].copy()
    data = _latest_per_player(data, source_name="injuries")
    return data[
        ["player_id", "injury_status", "practice_status", "primary_injury"]
    ].reset_index(drop=True)


def _unique_id_map(
    playerids: pd.DataFrame,
    *,
    source_column: str,
) -> dict[str, str]:
    if source_column not in playerids or "gsis_id" not in playerids:
        return {}
    source = _normalize_external_ids(playerids[source_column])
    gsis = _clean_text(playerids["gsis_id"])
    work = pd.DataFrame({"source": source, "gsis": gsis}).dropna()
    if work.empty:
        return {}
    # An external identifier earns authority only when it maps to exactly one GSIS identity.
    unique = work.groupby("source", dropna=False)["gsis"].agg(lambda values: tuple(sorted(set(values))))
    return {
        str(external_id): str(candidates[0])
        for external_id, candidates in unique.items()
        if len(candidates) == 1
    }


def _resolve_ranking_identities(
    rankings: pd.DataFrame,
    playerids: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, dict[str, Any]]:
    resolved = pd.Series(pd.NA, index=rankings.index, dtype="string")
    source_used = pd.Series(pd.NA, index=rankings.index, dtype="string")

    direct_column = _first_present(rankings, ("gsis_id", "player_id", "player_gsis_id"))
    if direct_column is not None:
        direct = _clean_text(rankings[direct_column])
        resolved.loc[direct.notna()] = direct.loc[direct.notna()]
        source_used.loc[direct.notna()] = f"direct:{direct_column}"

    routes = (
        ("id", "fantasypros_id", "fantasypros_id"),
        ("fantasypros_id", "fantasypros_id", "fantasypros_id"),
        ("sportsdata_id", "sportradar_id", "sportradar_id"),
        ("sportradar_id", "sportradar_id", "sportradar_id"),
        ("yahoo_id", "yahoo_id", "yahoo_id"),
    )
    route_maps = {
        route_name: _unique_id_map(playerids, source_column=playerids_column)
        for _, playerids_column, route_name in routes
    }
    conflicts = 0
    for index, row in rankings.iterrows():
        candidates: dict[str, str] = {}
        if pd.notna(resolved.at[index]):
            candidates[str(source_used.at[index])] = str(resolved.at[index])
        for ranking_column, _playerids_column, route_name in routes:
            if ranking_column not in rankings:
                continue
            key = _normalize_external_id(row.get(ranking_column))
            if key is None:
                continue
            mapped = route_maps[route_name].get(key)
            if mapped:
                candidates[route_name] = mapped
        unique_candidates = sorted(set(candidates.values()))
        if len(unique_candidates) == 1:
            resolved.at[index] = unique_candidates[0]
            routes_for_identity = sorted(
                route for route, candidate in candidates.items() if candidate == unique_candidates[0]
            )
            source_used.at[index] = "+".join(routes_for_identity)
        elif len(unique_candidates) > 1:
            resolved.at[index] = pd.NA
            source_used.at[index] = "CONFLICT"
            conflicts += 1

    total = int(len(rankings))
    resolved_rows = int(resolved.notna().sum())
    diagnostics = {
        "ranking_rows": total,
        "resolved_rows": resolved_rows,
        "unresolved_rows": total - resolved_rows,
        "identity_coverage": (resolved_rows / total if total else None),
        "conflict_rows": conflicts,
        "authority": "multi_id_exact_only_no_name_matching",
    }
    return resolved, source_used, diagnostics


def canonicalize_rankings(
    rankings: pd.DataFrame,
    playerids: pd.DataFrame | None = None,
) -> pd.DataFrame:
    columns = [
        "player_id",
        "market_rank",
        "market_adp",
        "market_rank_scope",
        "market_identity_source",
    ]
    if rankings.empty:
        out = pd.DataFrame(columns=columns)
        out.attrs["identity_diagnostics"] = {
            "ranking_rows": 0,
            "resolved_rows": 0,
            "unresolved_rows": 0,
            "identity_coverage": None,
            "conflict_rows": 0,
            "redraft_rows": 0,
            "resolved_redraft_rows": 0,
            "redraft_identity_coverage": None,
            "usable_market_players": 0,
            "authority": "multi_id_exact_only_no_name_matching",
        }
        return out

    data = rankings.copy()
    ids = playerids if playerids is not None else pd.DataFrame()
    resolved, identity_source, diagnostics = _resolve_ranking_identities(data, ids)
    data["player_id"] = resolved
    data["market_identity_source"] = identity_source
    data["market_rank"] = _numeric(
        data,
        ("rank", "overall_rank", "consensus_rank", "ecr", "draft_rank"),
    )
    data["market_adp"] = _numeric(
        data,
        ("adp", "consensus_adp", "market_adp", "avg_pick"),
    )

    ecr_type = _text(data, ("ecr_type",))
    data["market_rank_scope"] = pd.Series("unknown", index=data.index, dtype="string")
    if "ecr_type" in data:
        data.loc[ecr_type.eq("ro"), "market_rank_scope"] = "redraft_overall"
        data.loc[ecr_type.eq("rp"), "market_rank_scope"] = "redraft_position"
    if "page_type" in data:
        page_type = _clean_text(data["page_type"])
        redraft_page = page_type.str.startswith("redraft", na=False)
    else:
        redraft_page = pd.Series(False, index=data.index)

    # Prefer redraft overall, then redraft positional. Best-ball/dynasty rows are not substitutes.
    priority = pd.Series(99, index=data.index, dtype=int)
    priority.loc[ecr_type.eq("ro")] = 0
    priority.loc[ecr_type.eq("rp")] = 1
    priority.loc[redraft_page & priority.eq(99)] = 2
    data["__market_priority"] = priority
    redraft_rows = int(priority.lt(99).sum())
    resolved_redraft_rows = int((priority.lt(99) & data["player_id"].notna()).sum())
    diagnostics.update(
        {
            "redraft_rows": redraft_rows,
            "resolved_redraft_rows": resolved_redraft_rows,
            "redraft_identity_coverage": (
                resolved_redraft_rows / redraft_rows if redraft_rows else None
            ),
        }
    )
    data = data.loc[data["player_id"].notna() & data["__market_priority"].lt(99)].copy()
    if not data.empty:
        stable_fields = ["player_id", "__market_priority", "market_rank"]
        if "fp_page" in data:
            stable_fields.append("fp_page")
        data = data.sort_values(stable_fields, kind="mergesort", na_position="last")
        data = data.drop_duplicates("player_id", keep="first")
    out = data[columns].reset_index(drop=True)
    diagnostics["usable_market_players"] = int(len(out))
    out.attrs["identity_diagnostics"] = diagnostics
    return out


def canonicalize_projection_context(projections: pd.DataFrame) -> pd.DataFrame:
    if projections.empty or "player_id" not in projections:
        return pd.DataFrame(
            columns=["player_id", "projection_q50", "projection_vorp", "projection_model_version"]
        )
    data = projections.copy()
    data["player_id"] = _clean_text(data["player_id"])
    data["projection_q50"] = _numeric(
        data,
        ("valuation_points_q50", "season_points_q50", "fantasy_points_ppr_q50"),
    )
    data["projection_vorp"] = _numeric(data, ("vorp", "draft_value", "decision_value"))
    data["projection_model_version"] = _text(data, ("model_version",))
    data = data.loc[data["player_id"].notna()].copy()
    if data["player_id"].duplicated().any():
        raise ValueError("Projection context must contain unique player_id values.")
    return data[
        ["player_id", "projection_q50", "projection_vorp", "projection_model_version"]
    ].reset_index(drop=True)


def canonicalize_schedule(
    schedules: pd.DataFrame,
    *,
    season: int,
    as_of: datetime,
) -> list[dict[str, Any]]:
    if schedules.empty:
        return []
    data = schedules.copy()
    if "season" in data:
        data = data.loc[pd.to_numeric(data["season"], errors="coerce").eq(int(season))].copy()
    date_column = _first_present(data, ("gameday", "game_date", "date", "start_time"))
    if date_column is None or data.empty:
        return []
    dates = pd.to_datetime(data[date_column], errors="coerce", utc=True)
    today = as_of.astimezone(UTC).date()
    data = data.loc[dates.dt.date.ge(today)].copy()
    data["__game_date"] = dates.loc[data.index]
    if data.empty:
        return []
    data = data.sort_values("__game_date", kind="mergesort").head(12)
    rows: list[dict[str, Any]] = []
    for _, row in data.iterrows():
        rows.append(
            {
                "game_id": row.get("game_id"),
                "game_type": row.get("game_type"),
                "week": row.get("week"),
                "away_team": row.get("away_team"),
                "home_team": row.get("home_team"),
                "game_date": (
                    row["__game_date"].isoformat()
                    if pd.notna(row["__game_date"])
                    else None
                ),
            }
        )
    return rows


def _state_frame(
    rosters: pd.DataFrame,
    *,
    season: int,
    depth_charts: pd.DataFrame | None = None,
    injuries: pd.DataFrame | None = None,
    rankings: pd.DataFrame | None = None,
    playerids: pd.DataFrame | None = None,
    projections: pd.DataFrame | None = None,
) -> pd.DataFrame:
    state = canonicalize_rosters(rosters, season=season)
    joins = (
        canonicalize_depth_charts(
            depth_charts if depth_charts is not None else pd.DataFrame(),
            season=season,
        ),
        canonicalize_injuries(
            injuries if injuries is not None else pd.DataFrame(),
            season=season,
        ),
        canonicalize_rankings(
            rankings if rankings is not None else pd.DataFrame(),
            playerids if playerids is not None else pd.DataFrame(),
        ),
        canonicalize_projection_context(
            projections if projections is not None else pd.DataFrame()
        ),
    )
    for frame in joins:
        if not frame.empty:
            state = state.merge(frame, on="player_id", how="left", validate="one_to_one")
    return state.sort_values(
        ["team", "position", "player_name", "player_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def _changed(previous: object, current: object) -> bool:
    previous_missing = previous is None or pd.isna(previous)
    current_missing = current is None or pd.isna(current)
    if previous_missing and current_missing:
        return False
    if previous_missing != current_missing:
        return True
    if isinstance(previous, (int, float)) or isinstance(current, (int, float)):
        try:
            return not math.isclose(float(previous), float(current), rel_tol=0.0, abs_tol=1e-9)
        except (TypeError, ValueError):
            pass
    return str(previous) != str(current)


def _event(
    event_type: str,
    current: dict[str, Any] | None,
    previous: dict[str, Any] | None,
    *,
    significance: float,
    detail: str,
) -> dict[str, Any]:
    row = current or previous or {}
    return {
        "event_type": event_type,
        "player_id": row.get("player_id"),
        "player_name": row.get("player_name"),
        "team": row.get("team"),
        "position": row.get("position"),
        "significance": float(significance),
        "detail": detail,
        "before": previous,
        "after": current,
        "authority": HUB_AUTHORITY,
    }


def diff_player_states(previous: pd.DataFrame, current: pd.DataFrame) -> list[dict[str, Any]]:
    """Describe deterministic observed state changes without mutating projection authority."""

    previous_by_id = {
        str(row["player_id"]): row for row in frame_records(previous) if row.get("player_id")
    }
    current_by_id = {
        str(row["player_id"]): row for row in frame_records(current) if row.get("player_id")
    }
    events: list[dict[str, Any]] = []
    for player_id in sorted(set(previous_by_id) | set(current_by_id)):
        before = previous_by_id.get(player_id)
        after = current_by_id.get(player_id)
        if before is None and after is not None:
            events.append(
                _event(
                    "ROSTER_ADDED",
                    after,
                    None,
                    significance=0.95,
                    detail=f"Added to {after.get('team') or 'an NFL roster'}.",
                )
            )
            continue
        if after is None and before is not None:
            events.append(
                _event(
                    "ROSTER_REMOVED",
                    None,
                    before,
                    significance=0.98,
                    detail=f"No longer present on {before.get('team') or 'the prior roster snapshot'}.",
                )
            )
            continue
        assert before is not None and after is not None
        if _changed(before.get("team"), after.get("team")):
            events.append(
                _event(
                    "TEAM_CHANGED",
                    after,
                    before,
                    significance=1.0,
                    detail=f"Team changed from {before.get('team')} to {after.get('team')}.",
                )
            )
        if _changed(before.get("roster_status"), after.get("roster_status")):
            events.append(
                _event(
                    "ROSTER_STATUS_CHANGED",
                    after,
                    before,
                    significance=0.9,
                    detail=(
                        f"Roster status changed from {before.get('roster_status')} "
                        f"to {after.get('roster_status')}."
                    ),
                )
            )
        if _changed(before.get("injury_status"), after.get("injury_status")) or _changed(
            before.get("practice_status"), after.get("practice_status")
        ):
            events.append(
                _event(
                    "INJURY_STATUS_CHANGED",
                    after,
                    before,
                    significance=0.92,
                    detail=(
                        f"Injury/practice state changed: "
                        f"{before.get('injury_status') or before.get('practice_status')} → "
                        f"{after.get('injury_status') or after.get('practice_status')}."
                    ),
                )
            )
        before_depth = before.get("depth_rank")
        after_depth = after.get("depth_rank")
        if _changed(before_depth, after_depth):
            try:
                depth_delta = float(before_depth) - float(after_depth)
            except (TypeError, ValueError):
                depth_delta = 0.0
            events.append(
                _event(
                    "DEPTH_CHART_PROMOTION" if depth_delta > 0 else "DEPTH_CHART_DEMOTION",
                    after,
                    before,
                    significance=min(0.9, 0.6 + 0.1 * abs(depth_delta)),
                    detail=f"Depth rank changed from {before_depth} to {after_depth}.",
                )
            )
        before_rank = before.get("market_rank")
        after_rank = after.get("market_rank")
        try:
            market_delta = float(before_rank) - float(after_rank)
        except (TypeError, ValueError):
            market_delta = 0.0
        if abs(market_delta) >= 3.0:
            events.append(
                _event(
                    "MARKET_RANK_RISER" if market_delta > 0 else "MARKET_RANK_FALLER",
                    after,
                    before,
                    significance=min(0.85, 0.45 + abs(market_delta) / 50.0),
                    detail=f"Draft-market rank moved from {before_rank} to {after_rank}.",
                )
            )
    return sorted(
        events,
        key=lambda item: (-float(item["significance"]), str(item.get("player_name") or "")),
    )


def _source_health(
    *,
    name: str,
    available: bool,
    rows: int = 0,
    collected_at: datetime,
    error: str | None = None,
    required: bool = False,
) -> dict[str, Any]:
    return {
        "source": name,
        "available": bool(available),
        "required": bool(required),
        "rows": int(rows),
        "collected_at_utc": collected_at.astimezone(UTC).isoformat(),
        "error": error,
    }


def build_nfl_hub_snapshot(
    *,
    season: int,
    rosters: pd.DataFrame,
    depth_charts: pd.DataFrame | None = None,
    injuries: pd.DataFrame | None = None,
    rankings: pd.DataFrame | None = None,
    playerids: pd.DataFrame | None = None,
    schedules: pd.DataFrame | None = None,
    projections: pd.DataFrame | None = None,
    previous_snapshot: dict[str, Any] | None = None,
    source_health: list[dict[str, Any]] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = generated_at or datetime.now(UTC)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=UTC)
    raw_rankings = rankings if rankings is not None else pd.DataFrame()
    raw_playerids = playerids if playerids is not None else pd.DataFrame()
    ranking_view = canonicalize_rankings(raw_rankings, raw_playerids)
    market_identity = dict(ranking_view.attrs.get("identity_diagnostics", {}))
    current = _state_frame(
        rosters,
        season=season,
        depth_charts=depth_charts,
        injuries=injuries,
        rankings=raw_rankings,
        playerids=raw_playerids,
        projections=projections,
    )
    previous_rows = previous_snapshot.get("players", []) if previous_snapshot else []
    previous = pd.DataFrame(previous_rows)
    events = diff_player_states(previous, current) if not previous.empty else []
    health = list(source_health or [])
    required_failures = [
        item["source"] for item in health if item.get("required") and not item.get("available")
    ]
    optional_failures = [
        item["source"] for item in health if not item.get("required") and not item.get("available")
    ]
    if not raw_rankings.empty and int(market_identity.get("usable_market_players", 0) or 0) == 0:
        optional_failures.append("rankings_identity")
    return {
        "schema_version": HUB_SCHEMA_VERSION,
        "authority": HUB_AUTHORITY,
        "season": int(season),
        "generated_at_utc": generated.astimezone(UTC).isoformat(),
        "status": (
            "UNAVAILABLE"
            if required_failures
            else ("DEGRADED" if optional_failures else "READY")
        ),
        "required_source_failures": required_failures,
        "optional_source_failures": optional_failures,
        "source_health": health,
        "market_identity": market_identity,
        "player_count": int(len(current)),
        "players": frame_records(current),
        "events": events,
        "event_count": len(events),
        "upcoming_games": canonicalize_schedule(
            schedules if schedules is not None else pd.DataFrame(),
            season=season,
            as_of=generated,
        ),
        "model_note": (
            "NFL Hub events are observational state changes. Projection/model context is read-only "
            "and does not gain authority from a roster, news, injury, depth-chart, or market event."
        ),
    }


def _load_optional_projection(path: str | Path | None) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    candidate = Path(path)
    if not candidate.is_file():
        return pd.DataFrame()
    return read_table(candidate)


def acquire_live_nfl_hub_sources(
    season: int,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    """Acquire public nflverse sources with current rosters as the sole hard dependency."""

    try:
        import nflreadpy as nfl
    except ImportError as exc:
        raise RuntimeError("nflreadpy is required for NFL Hub refresh.") from exc

    collected = datetime.now(UTC)
    loaders: dict[str, tuple[Callable[[], object], bool]] = {
        "rosters": (lambda: nfl.load_rosters([int(season)]), True),
        "depth_charts": (lambda: nfl.load_depth_charts([int(season)]), False),
        "injuries": (lambda: nfl.load_injuries([int(season)]), False),
        "rankings": (lambda: nfl.load_ff_rankings(type="draft"), False),
        "playerids": (nfl.load_ff_playerids, False),
        "schedules": (lambda: nfl.load_schedules([int(season)]), False),
    }
    frames: dict[str, pd.DataFrame] = {}
    health: list[dict[str, Any]] = []
    for name, (loader, required) in loaders.items():
        try:
            frame = _to_pandas(loader())
        except Exception as exc:  # noqa: BLE001 - optional public sources degrade independently
            health.append(
                _source_health(
                    name=name,
                    available=False,
                    collected_at=collected,
                    error=str(exc),
                    required=required,
                )
            )
            if required:
                raise RuntimeError(f"Required NFL Hub source {name} failed: {exc}") from exc
            frames[name] = pd.DataFrame()
            continue
        frames[name] = frame
        health.append(
            _source_health(
                name=name,
                available=True,
                rows=len(frame),
                collected_at=collected,
                required=required,
            )
        )
    return frames, health


def load_nfl_hub_snapshot(root: str | Path) -> dict[str, Any] | None:
    path = Path(root) / "current.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def save_nfl_hub_snapshot(snapshot: dict[str, Any], root: str | Path) -> Path:
    destination = Path(root)
    destination.mkdir(parents=True, exist_ok=True)
    snapshots = destination / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    timestamp = str(snapshot.get("generated_at_utc") or datetime.now(UTC).isoformat())
    safe_timestamp = timestamp.replace(":", "").replace("+", "_")
    historical = snapshots / f"{safe_timestamp}.json"
    payload = json.dumps(snapshot, indent=2, sort_keys=True, allow_nan=False) + "\n"
    historical.write_text(payload, encoding="utf-8")
    current = destination / "current.json"
    temporary = current.with_name(f".{current.name}.{os.getpid()}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(current)
    return current


def refresh_nfl_hub(
    *,
    season: int,
    root: str | Path = "data/product/nfl_hub",
    projections_path: str | Path | None = "artifacts/predictions/product_player_values.csv",
) -> dict[str, Any]:
    previous = load_nfl_hub_snapshot(root)
    frames, health = acquire_live_nfl_hub_sources(season)
    snapshot = build_nfl_hub_snapshot(
        season=season,
        rosters=frames["rosters"],
        depth_charts=frames.get("depth_charts"),
        injuries=frames.get("injuries"),
        rankings=frames.get("rankings"),
        playerids=frames.get("playerids"),
        schedules=frames.get("schedules"),
        projections=_load_optional_projection(projections_path),
        previous_snapshot=previous,
        source_health=health,
    )
    save_nfl_hub_snapshot(snapshot, root)
    return snapshot
