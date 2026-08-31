from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from player_state_engine.data.io import read_table, write_table
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.rankings import match_rankings_to_players
from player_state_engine.integrations.fantasypros import FantasyProsClient

DEFAULT_LIVE_ADP_ROOT = Path("data/product/draft_market")
LIVE_ADP_SCHEMA_VERSION = 1
_REQUIRED_SNAPSHOTS = (("PPR", "ALL"), ("PPR", "OP"), ("HALF", "ALL"), ("HALF", "OP"))


def _scoring_code(config: LeagueConfig) -> str:
    scoring = str(config.scoring).strip().lower()
    if scoring in {"ppr", "full_ppr", "full"}:
        return "PPR"
    if scoring in {"half", "half_ppr", "half-ppr"}:
        return "HALF"
    return "STD"


def _market_scope(config: LeagueConfig) -> str:
    # FantasyPros exposes OP as the superflex-style overall market. It is a useful proxy for
    # multi-QB rooms, but the API does not certify an exact 2QB roster construction.
    return "OP" if config.is_multi_qb else "ALL"


def _format_confidence(config: LeagueConfig, scope: str) -> tuple[float, str, list[str]]:
    reasons = ["fantasypros_api_does_not_certify_team_count"]
    if config.is_multi_qb:
        if scope != "OP":
            return 0.0, "incompatible_multi_qb_market", [*reasons, "multi_qb_requires_op_market"]
        confidence = 0.58
        authority = "superflex_proxy_for_multi_qb"
        reasons.append("op_market_is_superflex_proxy_not_exact_2qb")
    else:
        if scope != "ALL":
            return 0.0, "incompatible_1qb_market", [*reasons, "one_qb_requires_all_market"]
        confidence = 0.82
        authority = "scoring_matched_1qb_market"

    # Generic ADP is not team-count-specific. Preserve it as useful timing evidence while shrinking
    # its influence for non-12-team rooms rather than fabricating an exact format match.
    if int(config.teams) != 12:
        confidence *= 0.86
        reasons.append(f"team_count_proxy_{int(config.teams)}_teams")
    return float(np.clip(confidence, 0.0, 1.0)), authority, reasons


def _effective_adp_sd(adp: float, format_confidence: float, identity_confidence: float) -> float:
    # The API's rank_std is dispersion across ranking/ADP sources, not an observed pick-position
    # standard deviation. Do not pass it to the normal survival approximation as if it were one.
    baseline = max(6.0, min(18.0, 5.0 + 0.055 * float(adp)))
    confidence = max(0.25, min(1.0, float(format_confidence) * float(identity_confidence)))
    return float(min(36.0, baseline / confidence))


def refresh_fantasypros_adp_snapshot(
    season: int,
    *,
    root: str | Path = DEFAULT_LIVE_ADP_ROOT,
    client: FantasyProsClient | None = None,
) -> dict[str, object]:
    """Fetch the four market views needed by the release-tested league families.

    Current market evidence is intentionally stored outside the immutable projection champion. A
    new ADP snapshot can therefore move pick timing without retraining or reapproving football
    projections. All requested views must succeed before ``current`` is replaced.
    """

    resolved_client = client or FantasyProsClient()
    frames: list[pd.DataFrame] = []
    snapshots: list[dict[str, object]] = []
    for scoring, scope in _REQUIRED_SNAPSHOTS:
        frame, metadata = resolved_client.fetch_consensus_rankings(
            int(season),
            position=scope,
            scoring=scoring,
            ranking_type="ADP",
            experts=False,
        )
        if frame.empty:
            raise RuntimeError(f"FantasyPros returned an empty {scoring}/{scope} ADP snapshot")
        frame = frame.copy()
        frame["market_scope"] = scope
        frame["market_scoring"] = scoring
        frames.append(frame)
        snapshots.append(
            {
                "scoring": scoring,
                "scope": scope,
                "rows": int(len(frame)),
                "last_updated": metadata.get("last_updated"),
                "last_updated_ts": metadata.get("last_updated_ts"),
                "ranking_type": metadata.get("ranking_type"),
                "source_teams": metadata.get("teams"),
                "source_qb_format": metadata.get("qb_format"),
            }
        )

    combined = pd.concat(frames, ignore_index=True)
    if set(combined["ranking_type"].astype(str).str.lower()) != {"adp"}:
        raise RuntimeError("FantasyPros market snapshot contains a non-ADP ranking type")
    if not set(combined["source_kind"].astype(str).str.lower()) <= {"market", "sharp_market"}:
        raise RuntimeError("FantasyPros ADP snapshot was not normalized as market evidence")

    output_root = Path(root)
    output_root.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC)
    metadata: dict[str, object] = {
        "schema_version": LIVE_ADP_SCHEMA_VERSION,
        "source": "fantasypros_adp",
        "authority": "external_market_overlay",
        "season": int(season),
        "generated_at_utc": generated_at.isoformat(),
        "snapshots": snapshots,
        "rows": int(len(combined)),
        "notes": [
            "ADP changes pick timing only; it does not change immutable football projection authority.",
            "FantasyPros rank_std is source dispersion and is not treated as observed pick-position SD.",
            "OP is a superflex-style proxy for multi-QB rooms; exact 2QB/team-count authority is not claimed.",
        ],
    }

    next_frame = output_root / "current.next.parquet"
    next_metadata = output_root / "current.metadata.next.json"
    final_frame = output_root / "current.parquet"
    final_metadata = output_root / "current.metadata.json"
    written = Path(write_table(combined, next_frame))
    next_metadata.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.replace(final_frame)
    next_metadata.replace(final_metadata)
    return {**metadata, "path": str(final_frame), "metadata_path": str(final_metadata)}


def load_live_adp_snapshot(
    root: str | Path = DEFAULT_LIVE_ADP_ROOT,
) -> tuple[pd.DataFrame, dict[str, object]]:
    output_root = Path(root)
    frame_path = output_root / "current.parquet"
    metadata_path = output_root / "current.metadata.json"
    if not frame_path.is_file() or not metadata_path.is_file():
        return pd.DataFrame(), {
            "available": False,
            "authority": "unavailable",
            "reason": "live_adp_snapshot_missing",
            "path": str(frame_path),
        }
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        frame = read_table(frame_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return pd.DataFrame(), {
            "available": False,
            "authority": "unavailable",
            "reason": "live_adp_snapshot_invalid",
            "error": str(exc),
            "path": str(frame_path),
        }
    if frame.empty:
        return frame, {
            **metadata,
            "available": False,
            "reason": "live_adp_snapshot_empty",
            "path": str(frame_path),
        }
    return frame, {**metadata, "available": True, "path": str(frame_path)}


def live_adp_status(root: str | Path = DEFAULT_LIVE_ADP_ROOT) -> dict[str, object]:
    frame, metadata = load_live_adp_snapshot(root)
    status = dict(metadata)
    status["rows"] = int(len(frame))
    generated = pd.to_datetime(status.get("generated_at_utc"), utc=True, errors="coerce")
    if pd.notna(generated):
        age = max(0.0, (pd.Timestamp.now(tz="UTC") - generated).total_seconds())
        status["age_seconds"] = float(age)
        status["stale"] = bool(age > 6 * 3600)
    else:
        status["age_seconds"] = None
        status["stale"] = None
    return status


def _identity_pool(projections: pd.DataFrame) -> pd.DataFrame:
    columns = ["player_id", "player_name", "position"]
    for optional in ("nfl_team", "recent_team"):
        if optional in projections.columns:
            columns.append(optional)
    pool = projections.loc[:, columns].copy()
    # A multicontract champion legitimately repeats one player across PPR and half-PPR. Identity
    # matching must happen once per player before the market signal is broadcast back to contracts.
    return pool.drop_duplicates("player_id", keep="first").reset_index(drop=True)


def attach_live_adp(
    projections: pd.DataFrame,
    config: LeagueConfig,
    market: pd.DataFrame,
    metadata: dict[str, object] | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Attach scoring-matched point-in-time ADP without changing projection bytes.

    The returned ``market_adp_sd`` is deliberately a conservative proxy uncertainty used only to
    soften the transparent survival approximation when the market format or identity match is not
    exact. It is not presented as an observed empirical pick-position standard deviation.
    """

    out = projections.copy()
    scope = _market_scope(config)
    scoring = _scoring_code(config)
    format_confidence, format_authority, format_reasons = _format_confidence(config, scope)
    base_status: dict[str, object] = {
        "available": False,
        "source": "fantasypros_adp",
        "authority": "external_market_overlay",
        "requested_scoring": scoring,
        "requested_scope": scope,
        "format_authority": format_authority,
        "format_confidence": format_confidence,
        "format_reasons": format_reasons,
        "generated_at_utc": (metadata or {}).get("generated_at_utc"),
    }
    if market.empty or out.empty or format_confidence <= 0:
        return out, {**base_status, "reason": "compatible_market_snapshot_unavailable"}

    required_market = {"source", "source_kind", "ranking_type", "scoring", "rank", "market_scope"}
    missing_market = required_market - set(market.columns)
    if missing_market:
        return out, {
            **base_status,
            "reason": "market_snapshot_schema_invalid",
            "missing_columns": sorted(missing_market),
        }
    if not {"player_id", "player_name", "position"}.issubset(out.columns):
        return out, {**base_status, "reason": "projection_identity_columns_missing"}

    selected = market.loc[
        market["source"].astype(str).str.lower().eq("fantasypros_adp")
        & market["source_kind"].astype(str).str.lower().eq("market")
        & market["ranking_type"].astype(str).str.lower().eq("adp")
        & market["scoring"].astype(str).str.upper().eq(scoring)
        & market["market_scope"].astype(str).str.upper().eq(scope)
    ].copy()
    if selected.empty:
        return out, {**base_status, "reason": "compatible_market_snapshot_unavailable"}

    identity_pool = _identity_pool(out)
    resolved = match_rankings_to_players(selected, identity_pool)
    matched = resolved.loc[
        resolved["matched_player_id"].notna()
        & pd.to_numeric(resolved["identity_match_confidence"], errors="coerce").ge(0.82)
    ].copy()
    if matched.empty:
        return out, {**base_status, "reason": "market_identity_matches_unavailable"}

    matched = matched.sort_values(
        ["matched_player_id", "identity_match_confidence", "captured_at_utc"],
        ascending=[True, False, False],
        kind="mergesort",
    ).drop_duplicates("matched_player_id", keep="first")
    lookup = matched.set_index(matched["matched_player_id"].astype(str))
    player_ids = out["player_id"].astype(str)
    adp = pd.to_numeric(player_ids.map(lookup["rank"]), errors="coerce")
    identity_conf = pd.to_numeric(
        player_ids.map(lookup["identity_match_confidence"]), errors="coerce"
    )
    captured = player_ids.map(lookup["captured_at_utc"])
    methods = player_ids.map(lookup["identity_match_method"])

    out["market_adp"] = adp
    out["market_adp_available"] = adp.notna()
    out["market_adp_source"] = "fantasypros_adp"
    out["market_adp_authority"] = "external_market_overlay"
    out["market_adp_scope"] = scope
    out["market_adp_format_authority"] = format_authority
    out["market_adp_format_confidence"] = format_confidence
    out["market_adp_identity_confidence"] = identity_conf
    out["market_adp_identity_method"] = methods
    out["market_adp_captured_at_utc"] = captured
    out["market_adp_sd"] = [
        _effective_adp_sd(value, format_confidence, identity)
        if np.isfinite(value) and np.isfinite(identity)
        else np.nan
        for value, identity in zip(adp, identity_conf, strict=False)
    ]
    out["market_adp_sd_authority"] = "conservative_format_proxy_not_observed_pick_sd"

    skill_positions = out["position"].astype(str).str.upper().isin(["QB", "RB", "WR", "TE"])
    eligible_player_ids = set(out.loc[skill_positions, "player_id"].astype(str))
    matched_player_ids = set(out.loc[out["market_adp_available"], "player_id"].astype(str))
    matched_count = len(matched_player_ids & eligible_player_ids)
    denominator = len(eligible_player_ids)
    coverage = float(matched_count / denominator) if denominator else 0.0
    return out, {
        **base_status,
        "available": True,
        "matched_players": matched_count,
        "eligible_players": denominator,
        "coverage_rate": coverage,
        "unresolved_market_rows": int(resolved["matched_player_id"].isna().sum()),
        "low_confidence_market_rows": int(
            (
                resolved["matched_player_id"].notna()
                & pd.to_numeric(resolved["identity_match_confidence"], errors="coerce").lt(0.82)
            ).sum()
        ),
        "adp_sd_authority": "conservative_format_proxy_not_observed_pick_sd",
    }
