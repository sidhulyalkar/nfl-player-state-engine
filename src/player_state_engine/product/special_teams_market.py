from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd

from player_state_engine.product.nfl_hub import (
    _resolve_ranking_identities,
    canonicalize_rosters,
)
from player_state_engine.product.provenance import frame_records

SPECIAL_TEAMS_MARKET_AUTHORITY = "external_market_only"
SPECIAL_TEAMS_MARKET_SOURCE = "fantasypros_redraft_positional_ecr"

_TEAM_ALIASES = {
    "JAC": "JAX",
    "LAR": "LA",
}


def _text(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip()
    return values.mask(values.str.lower().isin({"", "nan", "none", "<na>"}))


def _team(series: pd.Series) -> pd.Series:
    values = _text(series).str.upper()
    return values.replace(_TEAM_ALIASES)


def _position_rows(rankings: pd.DataFrame, position: str) -> pd.DataFrame:
    if rankings.empty:
        return pd.DataFrame()
    required = {"pos", "ecr_type", "ecr"}
    if not required.issubset(rankings.columns):
        return pd.DataFrame()
    pos = _text(rankings["pos"]).str.upper()
    ecr_type = _text(rankings["ecr_type"]).str.lower()
    data = rankings.loc[pos.eq(position) & ecr_type.eq("rp")].copy()
    if "page_type" in data:
        page_type = _text(data["page_type"]).str.lower()
        data = data.loc[page_type.eq(f"redraft-{position.lower()}")].copy()
    if data.empty:
        return data
    data["positional_ecr"] = pd.to_numeric(data["ecr"], errors="coerce")
    data["rank_sd"] = pd.to_numeric(data["sd"], errors="coerce") if "sd" in data else pd.NA
    data["best_rank"] = (
        pd.to_numeric(data["best"], errors="coerce") if "best" in data else pd.NA
    )
    data["worst_rank"] = (
        pd.to_numeric(data["worst"], errors="coerce") if "worst" in data else pd.NA
    )
    data["source_date"] = _text(data["scrape_date"]) if "scrape_date" in data else pd.NA
    return data.loc[data["positional_ecr"].notna()].copy()


def _dedupe_latest(data: pd.DataFrame, key: str) -> pd.DataFrame:
    if data.empty:
        return data.copy()
    work = data.copy()
    if "source_date" in work:
        work["__source_date"] = pd.to_datetime(work["source_date"], errors="coerce", utc=True)
        work = work.sort_values(
            [key, "__source_date", "positional_ecr"],
            kind="mergesort",
            na_position="first",
        )
        work = work.drop_duplicates(key, keep="last").drop(columns=["__source_date"])
    elif work[key].duplicated().any():
        raise ValueError(f"Ambiguous duplicate special-teams market key: {key}")
    return work


def _kicker_board(
    rankings: pd.DataFrame,
    playerids: pd.DataFrame,
    rosters: pd.DataFrame,
    *,
    season: int,
) -> pd.DataFrame:
    kickers = _position_rows(rankings, "K")
    if kickers.empty:
        return pd.DataFrame()
    resolved, identity_source, _ = _resolve_ranking_identities(kickers, playerids)
    kickers["player_id"] = resolved
    kickers["identity_source"] = identity_source
    kickers = kickers.loc[kickers["player_id"].notna()].copy()
    if kickers.empty:
        return kickers

    current = canonicalize_rosters(rosters, season=season)
    current = current.loc[current["position"].astype(str).str.upper().eq("K")].copy()
    current = current[["player_id", "player_name", "team", "roster_status"]]
    kickers = kickers.merge(current, on="player_id", how="inner", validate="many_to_one")
    kickers = _dedupe_latest(kickers, "player_id")
    kickers = kickers.sort_values(
        ["positional_ecr", "player_name", "player_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    kickers["market_order"] = range(1, len(kickers) + 1)
    kickers["entity_id"] = "K:" + kickers["player_id"].astype(str)
    kickers["entity_type"] = "player"
    kickers["position"] = "K"
    kickers["authority"] = SPECIAL_TEAMS_MARKET_AUTHORITY
    kickers["market_source"] = SPECIAL_TEAMS_MARKET_SOURCE
    return kickers[
        [
            "entity_id",
            "entity_type",
            "position",
            "player_id",
            "player_name",
            "team",
            "roster_status",
            "market_order",
            "positional_ecr",
            "rank_sd",
            "best_rank",
            "worst_rank",
            "source_date",
            "identity_source",
            "market_source",
            "authority",
        ]
    ]


def _dst_board(rankings: pd.DataFrame) -> pd.DataFrame:
    defenses = _position_rows(rankings, "DST")
    if defenses.empty:
        return pd.DataFrame()
    if "team" not in defenses:
        raise ValueError("DST rankings require team identity.")
    defenses["team"] = _team(defenses["team"])
    defenses["entity_name"] = (
        _text(defenses["player"])
        if "player" in defenses
        else "DST " + defenses["team"].astype("string")
    )
    defenses = defenses.loc[defenses["team"].notna()].copy()
    defenses = _dedupe_latest(defenses, "team")
    defenses = defenses.sort_values(
        ["positional_ecr", "team"],
        kind="mergesort",
    ).reset_index(drop=True)
    defenses["market_order"] = range(1, len(defenses) + 1)
    defenses["entity_id"] = "DST:" + defenses["team"].astype(str)
    defenses["entity_type"] = "team_defense"
    defenses["position"] = "DST"
    defenses["authority"] = SPECIAL_TEAMS_MARKET_AUTHORITY
    defenses["market_source"] = SPECIAL_TEAMS_MARKET_SOURCE
    return defenses[
        [
            "entity_id",
            "entity_type",
            "position",
            "entity_name",
            "team",
            "market_order",
            "positional_ecr",
            "rank_sd",
            "best_rank",
            "worst_rank",
            "source_date",
            "market_source",
            "authority",
        ]
    ]


def build_special_teams_market(
    rankings: pd.DataFrame,
    playerids: pd.DataFrame,
    rosters: pd.DataFrame,
    *,
    season: int,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build market-only K/DST guidance without manufacturing model valuation authority."""

    generated = generated_at or datetime.now(UTC)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=UTC)
    generated = generated.astimezone(UTC)

    kickers = _kicker_board(rankings, playerids, rosters, season=season)
    defenses = _dst_board(rankings)
    source_dates = pd.concat(
        [
            kickers.get("source_date", pd.Series(dtype="string")),
            defenses.get("source_date", pd.Series(dtype="string")),
        ],
        ignore_index=True,
    ).dropna()
    source_date = str(source_dates.max()) if not source_dates.empty else None
    return {
        "schema_version": 1,
        "authority": SPECIAL_TEAMS_MARKET_AUTHORITY,
        "market_source": SPECIAL_TEAMS_MARKET_SOURCE,
        "season": int(season),
        "generated_at_utc": generated.isoformat(),
        "source_date": source_date,
        "kicker_count": int(len(kickers)),
        "dst_count": int(len(defenses)),
        "kickers": frame_records(kickers),
        "defenses": frame_records(defenses),
        "model_fields_present": False,
        "note": (
            "Kicker and DST entries are redraft positional market consensus only. They are not "
            "production model projections, exact-scored fantasy distributions, VORP, or overall "
            "draft ranks. DST identity is the NFL team; kicker identity is exact GSIS player ID."
        ),
    }
