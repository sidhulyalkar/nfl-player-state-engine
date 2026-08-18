from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from player_state_engine.data.io import read_table
from player_state_engine.fantasy.decision_board import DecisionType, build_decision_board
from player_state_engine.fantasy.rankings import (
    attach_external_ranking_context,
    format_signature,
    load_ranking_snapshots,
)
from player_state_engine.integrations.portfolio import league_config_from_snapshot
from player_state_engine.integrations.ranking_sources import ranking_source_catalog
from player_state_engine.product.provenance import frame_records
from player_state_engine.product.store import LeagueSnapshotStore

try:
    from fastapi import FastAPI, HTTPException, Query
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


def _scoring_status(board: pd.DataFrame, unsupported: list[str]) -> dict[str, object]:
    if board.empty:
        return {
            "exact_share": None,
            "fallback_share": None,
            "sources": [],
            "unsupported_live_scoring_keys": unsupported,
        }
    fallback = (
        board["league_scoring_fallback"].astype(bool)
        if "league_scoring_fallback" in board
        else pd.Series(True, index=board.index)
    )
    sources = (
        sorted(board["league_scoring_source"].dropna().astype(str).unique().tolist())
        if "league_scoring_source" in board
        else []
    )
    return {
        "exact_share": float((~fallback).mean()),
        "fallback_share": float(fallback.mean()),
        "sources": sources,
        "unsupported_live_scoring_keys": unsupported,
        "scoring_exact": bool(not fallback.any() and not unsupported),
    }


def install_ranking_routes(
    app: FastAPI,
    *,
    store_root: str | Path | None = None,
    projections_path: str | Path | None = None,
    ranking_root: str | Path | None = None,
) -> None:
    store = LeagueSnapshotStore(
        store_root or os.getenv("PSE_LEAGUE_STORE", "data/product/leagues")
    )
    projection_location = Path(
        projections_path
        or os.getenv("PSE_PROJECTIONS_PATH", "artifacts/predictions/product_player_values.csv")
    )
    ranking_location = Path(
        ranking_root or os.getenv("PSE_RANKING_SNAPSHOTS_DIR", "data/external/rankings")
    )

    @app.get("/v1/rankings/sources")
    def ranking_sources() -> dict[str, object]:
        snapshots = load_ranking_snapshots(ranking_location)
        installed = (
            snapshots.groupby(["source", "source_kind"], dropna=False)
            .agg(
                rows=("rank", "size"),
                latest_capture=("captured_at_utc", "max"),
                ranking_types=("ranking_type", lambda values: sorted(set(map(str, values)))),
            )
            .reset_index()
            if not snapshots.empty
            else pd.DataFrame()
        )
        return {
            "catalog": ranking_source_catalog(),
            "snapshot_root": str(ranking_location),
            "installed": frame_records(installed),
            "external_values_are_audit_only": True,
        }

    @app.get("/v1/leagues/{league_id}/rankings/audit")
    def ranking_audit(
        league_id: str,
        limit: int = Query(default=250, ge=1, le=1000),
    ) -> dict[str, object]:
        try:
            snapshot = store.load(league_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not projection_location.exists():
            raise HTTPException(
                status_code=503,
                detail=f"Projection artifact unavailable: {projection_location}",
            )
        projections = read_table(projection_location)
        if projections.empty:
            raise HTTPException(status_code=503, detail="Projection artifact is empty.")
        config = league_config_from_snapshot(snapshot)
        board = build_decision_board(projections, config, DecisionType.DRAFT)
        rankings = load_ranking_snapshots(ranking_location)
        enriched, metadata = attach_external_ranking_context(board, rankings, config)
        rank_column = "overall_rank" if "overall_rank" in enriched else "decision_specific_score"
        enriched = enriched.sort_values(
            rank_column,
            ascending=rank_column != "decision_specific_score",
            kind="mergesort",
        )
        unsupported = list(snapshot.metadata.get("unsupported_scoring_keys") or [])
        columns = [
            column
            for column in (
                "player_id",
                "player_name",
                "position",
                "overall_rank",
                "position_rank",
                "valuation_points_q10",
                "valuation_points_q50",
                "valuation_points_q90",
                "vorp",
                "replacement_rank",
                "league_starter_demand",
                "dynamic_scarcity_score",
                "league_scoring_source",
                "league_scoring_coverage",
                "league_scoring_fallback",
                "external_consensus_rank",
                "external_rank_sd",
                "external_rank_min",
                "external_rank_max",
                "external_source_count",
                "market_consensus_adp",
                "market_rank_sd",
                "market_source_count",
                "model_vs_external_rank_delta",
                "external_disagreement_score",
            )
            if column in enriched
        ]
        return {
            "league_id": league_id,
            "format": format_signature(config),
            "scoring_status": _scoring_status(enriched, unsupported),
            "ranking_context": metadata,
            "rows": frame_records(enriched.loc[:, columns].head(int(limit))),
        }
