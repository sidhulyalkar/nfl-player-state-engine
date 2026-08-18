from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from player_state_engine.data.io import read_table
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.integrations.ranking_sources import source_spec

_CANONICAL_COLUMNS = (
    "source",
    "source_kind",
    "source_player_id",
    "canonical_player_id",
    "player_name",
    "position",
    "nfl_team",
    "ranking_type",
    "scoring",
    "teams",
    "qb_format",
    "rank",
    "position_rank",
    "rank_min",
    "rank_max",
    "rank_std",
    "expert_count",
    "source_weight",
    "captured_at_utc",
    "source_url",
)

_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "source_player_id": ("source_player_id", "player_id", "id", "fantasypros_id"),
    "canonical_player_id": ("canonical_player_id", "gsis_id", "nflverse_id"),
    "player_name": ("player_name", "name", "player"),
    "position": ("position", "pos"),
    "nfl_team": ("nfl_team", "team", "team_id", "player_team_id"),
    "rank": ("rank", "rank_ecr", "overall_rank", "ecr"),
    "position_rank": ("position_rank", "pos_rank", "rank_position"),
    "rank_min": ("rank_min", "min_rank", "ecr_min"),
    "rank_max": ("rank_max", "max_rank", "ecr_max"),
    "rank_std": ("rank_std", "std", "rank_stdev", "ecr_std"),
    "expert_count": ("expert_count", "experts", "count"),
}

_TEAM_ALIASES = {
    "JAC": "JAX",
    "WSH": "WAS",
    "LVR": "LV",
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
}


def _normalize_name(value: object) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.lower().replace("’", "'")
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?\b", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _normalize_team(value: object) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    team = str(value).strip().upper()
    return _TEAM_ALIASES.get(team, team)


def _normalize_position(value: object) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    return str(value).strip().upper().replace("D/ST", "DEF").replace("DST", "DEF")


def qb_format(config: LeagueConfig) -> str:
    mandatory = int(config.roster_slots.get("QB", 0))
    superflex = sum(
        count
        for slot, count in config.flex_slots.items()
        if "QB" in config.flex_eligibility.get(slot, ())
    )
    if mandatory >= 2:
        return "2qb"
    if superflex > 0:
        return "superflex"
    return "1qb"


def format_signature(config: LeagueConfig) -> dict[str, object]:
    return {
        "teams": int(config.teams),
        "scoring": str(config.scoring).lower(),
        "qb_format": qb_format(config),
        "roster_slots": dict(sorted(config.roster_slots.items())),
        "tight_end_premium": float(config.tight_end_premium),
        "median_scoring": bool(config.median_scoring),
    }


def _first_column(frame: pd.DataFrame, aliases: tuple[str, ...]) -> pd.Series:
    for column in aliases:
        if column in frame:
            return frame[column]
    return pd.Series(np.nan, index=frame.index)


def normalize_ranking_frame(
    frame: pd.DataFrame,
    *,
    source: str,
    source_kind: str | None = None,
    ranking_type: str = "draft",
    scoring: str = "unknown",
    teams: int | None = None,
    qb_format_name: str = "unknown",
    source_weight: float = 1.0,
    captured_at_utc: datetime | str | None = None,
    source_url: str | None = None,
) -> pd.DataFrame:
    """Normalize an external ranking/ADP snapshot without giving it model authority."""
    if frame.empty:
        return pd.DataFrame(columns=_CANONICAL_COLUMNS)
    spec = source_spec(source)
    resolved_kind = source_kind or (spec.source_kind if spec else "expert")
    captured = pd.Timestamp(captured_at_utc or datetime.now(UTC))
    if captured.tzinfo is None:
        captured = captured.tz_localize("UTC")
    else:
        captured = captured.tz_convert("UTC")

    out = pd.DataFrame(index=frame.index)
    for target, aliases in _COLUMN_ALIASES.items():
        out[target] = _first_column(frame, aliases)
    if out["rank"].isna().all():
        raise ValueError("External ranking snapshot must contain an overall rank column.")

    out["source"] = str(source).strip().lower()
    out["source_kind"] = str(resolved_kind).strip().lower()
    out["ranking_type"] = str(ranking_type).strip().lower()
    out["scoring"] = str(scoring).strip().lower()
    out["teams"] = int(teams) if teams is not None else np.nan
    out["qb_format"] = str(qb_format_name).strip().lower()
    out["source_weight"] = max(0.0, float(source_weight))
    out["captured_at_utc"] = captured
    out["source_url"] = source_url
    out["player_name"] = out["player_name"].map(lambda value: "" if pd.isna(value) else str(value))
    out["position"] = out["position"].map(_normalize_position)
    out["nfl_team"] = out["nfl_team"].map(_normalize_team)
    for column in (
        "rank",
        "position_rank",
        "rank_min",
        "rank_max",
        "rank_std",
        "expert_count",
    ):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.loc[out["rank"].notna()].copy()
    out["rank"] = out["rank"].astype(float)
    out["source_player_id"] = out["source_player_id"].where(
        out["source_player_id"].notna(), None
    )
    out["canonical_player_id"] = out["canonical_player_id"].where(
        out["canonical_player_id"].notna(), None
    )
    return out.loc[:, _CANONICAL_COLUMNS].reset_index(drop=True)


def load_ranking_snapshots(root: str | Path) -> pd.DataFrame:
    root = Path(root)
    if not root.exists():
        return pd.DataFrame(columns=_CANONICAL_COLUMNS)
    frames: list[pd.DataFrame] = []
    for path in sorted([*root.rglob("*.csv"), *root.rglob("*.parquet")]):
        try:
            frame = read_table(path)
        except Exception:  # noqa: BLE001 - one bad optional snapshot must not break draft day.
            continue
        if set(_CANONICAL_COLUMNS).issubset(frame.columns):
            frames.append(frame.loc[:, _CANONICAL_COLUMNS].copy())
    return (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=_CANONICAL_COLUMNS)
    )


def match_rankings_to_players(rankings: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    """Resolve external identities conservatively and report match method/confidence."""
    if rankings.empty:
        result = rankings.copy()
        result["matched_player_id"] = pd.Series(dtype=str)
        result["identity_match_method"] = pd.Series(dtype=str)
        result["identity_match_confidence"] = pd.Series(dtype=float)
        return result
    required = {"player_id", "player_name", "position"}
    missing = required - set(players)
    if missing:
        raise ValueError(f"Player identity frame missing columns: {sorted(missing)}")

    pool = players.copy()
    pool["_id"] = pool["player_id"].astype(str)
    pool["_name"] = pool["player_name"].map(_normalize_name)
    pool["_position"] = pool["position"].map(_normalize_position)
    if "nfl_team" in pool:
        pool["_team"] = pool["nfl_team"].map(_normalize_team)
    elif "recent_team" in pool:
        pool["_team"] = pool["recent_team"].map(_normalize_team)
    else:
        pool["_team"] = ""

    ids = set(pool["_id"])
    exact_name_position_team: dict[tuple[str, str, str], list[str]] = {}
    exact_name_position: dict[tuple[str, str], list[str]] = {}
    for _, row in pool.iterrows():
        player_id = str(row["_id"])
        name = str(row["_name"])
        position = str(row["_position"])
        team = str(row["_team"])
        exact_name_position_team.setdefault((name, position, team), []).append(player_id)
        exact_name_position.setdefault((name, position), []).append(player_id)

    matched_ids: list[str | None] = []
    methods: list[str] = []
    confidences: list[float] = []
    for _, row in rankings.iterrows():
        canonical = row.get("canonical_player_id")
        source_id = row.get("source_player_id")
        candidate = (
            str(canonical)
            if canonical is not None and pd.notna(canonical) and str(canonical)
            else None
        )
        if candidate and candidate in ids:
            matched_ids.append(candidate)
            methods.append("canonical_id")
            confidences.append(1.0)
            continue
        candidate = (
            str(source_id)
            if source_id is not None and pd.notna(source_id) and str(source_id)
            else None
        )
        if candidate and candidate in ids:
            matched_ids.append(candidate)
            methods.append("source_id_exact")
            confidences.append(0.98)
            continue
        name = _normalize_name(row.get("player_name", ""))
        position = _normalize_position(row.get("position", ""))
        team = _normalize_team(row.get("nfl_team", ""))
        key3 = exact_name_position_team.get((name, position, team), []) if team else []
        if len(key3) == 1:
            matched_ids.append(key3[0])
            methods.append("name_position_team")
            confidences.append(0.93)
            continue
        key2 = exact_name_position.get((name, position), [])
        if len(key2) == 1:
            matched_ids.append(key2[0])
            methods.append("name_position_unique")
            confidences.append(0.82)
            continue
        matched_ids.append(None)
        methods.append("unresolved")
        confidences.append(0.0)

    result = rankings.copy()
    result["matched_player_id"] = matched_ids
    result["identity_match_method"] = methods
    result["identity_match_confidence"] = confidences
    return result


def _format_distance(row: pd.Series, config: LeagueConfig) -> float:
    signature = format_signature(config)
    score = 0.0
    row_teams = pd.to_numeric(pd.Series([row.get("teams")]), errors="coerce").iloc[0]
    if pd.isna(row_teams):
        score += 0.35
    else:
        score += min(abs(float(row_teams) - config.teams) / max(config.teams, 1), 1.5)
    scoring = str(row.get("scoring") or "unknown").lower()
    if scoring in {"", "unknown", "nan", "none"}:
        score += 0.25
    elif scoring != signature["scoring"]:
        score += 0.90
    qbf = str(row.get("qb_format") or "unknown").lower()
    if qbf in {"", "unknown", "nan", "none"}:
        score += 0.40
    elif qbf != signature["qb_format"]:
        score += 2.0
    return float(score)


def select_format_rankings(rankings: pd.DataFrame, config: LeagueConfig) -> pd.DataFrame:
    """Choose the closest available snapshot per source/player without inventing format equivalence."""
    if rankings.empty:
        return rankings.copy()
    data = rankings.copy()
    data["format_distance"] = data.apply(lambda row: _format_distance(row, config), axis=1)
    data["captured_at_utc"] = pd.to_datetime(
        data["captured_at_utc"], utc=True, errors="coerce"
    )
    keys = ["source", "matched_player_id", "ranking_type"]
    data = data.sort_values(
        [*keys, "format_distance", "captured_at_utc"],
        ascending=[True, True, True, True, False],
        kind="mergesort",
    )
    data = data.drop_duplicates(keys, keep="first")
    data["format_match_confidence"] = np.exp(-data["format_distance"]).clip(0.0, 1.0)
    return data.reset_index(drop=True)


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & weights.gt(0)
    if not bool(valid.any()):
        return float("nan")
    return float(
        np.average(values.loc[valid].astype(float), weights=weights.loc[valid].astype(float))
    )


def attach_external_ranking_context(
    board: pd.DataFrame,
    rankings: pd.DataFrame,
    config: LeagueConfig,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Attach external expert/market disagreement as audit context only.

    No returned external field is consumed by ``live_draft_score``. The product can therefore
    show where the model disagrees with consensus without accidentally converting consensus into
    ground truth.
    """
    out = board.copy()
    if rankings.empty or out.empty:
        out["external_consensus_rank"] = np.nan
        out["external_rank_sd"] = np.nan
        out["external_source_count"] = 0
        out["market_consensus_adp"] = np.nan
        out["market_rank_sd"] = np.nan
        out["market_source_count"] = 0
        out["model_vs_external_rank_delta"] = np.nan
        out["external_disagreement_score"] = 0.0
        return out, {"available": False, "sources": [], "matched_rows": 0}

    resolved = match_rankings_to_players(rankings, out)
    unresolved_count = int(resolved["matched_player_id"].isna().sum())
    matched = resolved.loc[resolved["matched_player_id"].notna()].copy()
    selected = select_format_rankings(matched, config)
    expert = selected.loc[selected["source_kind"].eq("expert")].copy()
    market = selected.loc[selected["source_kind"].isin(["market", "sharp_market"])].copy()

    rows: list[dict[str, Any]] = []
    for player_id, group in selected.groupby("matched_player_id", sort=False):
        expert_group = group.loc[group["source_kind"].eq("expert")]
        weights = (
            pd.to_numeric(expert_group["source_weight"], errors="coerce").fillna(1.0)
            * pd.to_numeric(
                expert_group["format_match_confidence"], errors="coerce"
            ).fillna(0.0)
            * pd.to_numeric(
                expert_group["identity_match_confidence"], errors="coerce"
            ).fillna(0.0)
        )
        ranks = pd.to_numeric(expert_group["rank"], errors="coerce")
        consensus = _weighted_mean(ranks, weights)
        market_group = group.loc[group["source_kind"].isin(["market", "sharp_market"])]
        market_rank = pd.to_numeric(market_group["rank"], errors="coerce")
        rows.append(
            {
                "player_id": str(player_id),
                "external_consensus_rank": consensus,
                "external_rank_sd": (
                    float(ranks.std(ddof=0)) if ranks.notna().any() else np.nan
                ),
                "external_rank_min": float(ranks.min()) if ranks.notna().any() else np.nan,
                "external_rank_max": float(ranks.max()) if ranks.notna().any() else np.nan,
                "external_source_count": int(expert_group["source"].nunique()),
                "market_consensus_adp": (
                    float(market_rank.mean()) if market_rank.notna().any() else np.nan
                ),
                "market_rank_sd": (
                    float(market_rank.std(ddof=0)) if market_rank.notna().any() else np.nan
                ),
                "market_source_count": int(market_group["source"].nunique()),
            }
        )
    context = pd.DataFrame(rows)
    if not context.empty:
        out = out.merge(context, on="player_id", how="left", validate="one_to_one")
    else:
        out["external_consensus_rank"] = np.nan
        out["external_rank_sd"] = np.nan
        out["external_rank_min"] = np.nan
        out["external_rank_max"] = np.nan
        out["external_source_count"] = 0
        out["market_consensus_adp"] = np.nan
        out["market_rank_sd"] = np.nan
        out["market_source_count"] = 0
    out["external_source_count"] = out["external_source_count"].fillna(0).astype(int)
    out["market_source_count"] = out["market_source_count"].fillna(0).astype(int)
    rank_column = (
        "live_rank"
        if "live_rank" in out
        else "overall_rank"
        if "overall_rank" in out
        else None
    )
    model_rank = (
        pd.to_numeric(out[rank_column], errors="coerce")
        if rank_column
        else out["live_draft_score"].rank(method="average", ascending=False)
    )
    # Positive means the model is more bullish: e.g. model #8 vs external #18 -> +10.
    out["model_vs_external_rank_delta"] = out["external_consensus_rank"] - model_rank
    out["external_disagreement_score"] = (
        pd.to_numeric(out["external_rank_sd"], errors="coerce").fillna(0.0) / 20.0
    ).clip(0, 1)
    metadata = {
        "available": bool(len(selected)),
        "sources": sorted(selected["source"].dropna().astype(str).unique().tolist()),
        "expert_sources": sorted(expert["source"].dropna().astype(str).unique().tolist()),
        "market_sources": sorted(market["source"].dropna().astype(str).unique().tolist()),
        "matched_rows": int(len(selected)),
        "unresolved_rows": unresolved_count,
        "format_signature": format_signature(config),
        "external_values_are_audit_only": True,
    }
    return out, metadata
