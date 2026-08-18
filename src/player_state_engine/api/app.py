from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from player_state_engine.data.io import read_table
from player_state_engine.fantasy.decision_board import DecisionType, build_decision_board
from player_state_engine.fantasy.decisions import optimize_lineup, rank_waiver_candidates
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.integrations.portfolio import league_config_from_snapshot
from player_state_engine.integrations.sleeper import SleeperImporter
from player_state_engine.product.league_picture import (
    attach_ownership,
    league_power_rankings,
    roster_needs,
)
from player_state_engine.product.nfl_state import build_nfl_state
from player_state_engine.product.provenance import (
    frame_records,
    identity_coverage,
    projection_metadata,
)
from player_state_engine.product.research import ResearchArtifacts, team_context_response
from player_state_engine.product.schemas import LeagueSnapshot, TradeAnalysisRequest
from player_state_engine.product.store import LeagueSnapshotStore
from player_state_engine.product.trades import analyze_trade, suggest_trades

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as exc:  # pragma: no cover - optional dependency boundary
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


def _load_optional_table(path: str | Path | None) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    candidate = Path(path)
    return read_table(candidate) if candidate.exists() else pd.DataFrame()


def _league_config(snapshot: LeagueSnapshot) -> LeagueConfig:
    """Use the same authoritative live league translation as the Draft War Room."""
    config = league_config_from_snapshot(snapshot)
    if snapshot.settings.faab_budget is not None:
        config.faab_budget = float(snapshot.settings.faab_budget)
    if snapshot.settings.playoff_week_start is not None:
        config.playoff_weeks = tuple(range(int(snapshot.settings.playoff_week_start), 18))
    return config


def create_app(
    *,
    store_root: str | Path | None = None,
    projections_path: str | Path | None = None,
    schedules_path: str | Path | None = None,
    benchmark_root: str | Path | None = None,
    conformal_root: str | Path | None = None,
    opportunity_root: str | Path | None = None,
    historical_source_root: str | Path | None = None,
    team_context_path: str | Path | None = None,
    schedules_data_mode: str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="NFL Player State Engine Product API",
        version="0.9.0",
        description="League imports, probabilistic player cards, trade analysis and fantasy decisions.",
    )
    origins = [
        origin.strip()
        for origin in os.getenv("PSE_CORS_ORIGINS", "http://localhost:5173").split(",")
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    store = LeagueSnapshotStore(
        store_root or os.getenv("PSE_LEAGUE_STORE", "data/product/leagues")
    )
    projection_location = projections_path or os.getenv(
        "PSE_PROJECTIONS_PATH", "artifacts/predictions/product_player_values.csv"
    )
    schedule_location = schedules_path or os.getenv(
        "PSE_SCHEDULES_PATH", "data/raw/nflverse/schedules.csv"
    )
    schedule_mode = (
        schedules_data_mode or os.getenv("PSE_SCHEDULES_DATA_MODE", "UNVERIFIED")
    ).upper()
    team_context_location = team_context_path or os.getenv(
        "PSE_TEAM_CONTEXT_PATH", "data/processed/team_play_structure_2025.parquet"
    )
    research = ResearchArtifacts(
        benchmark_root=benchmark_root
        or os.getenv("PSE_BENCHMARK_ROOT", "artifacts/reports/benchmark_real"),
        conformal_root=conformal_root
        or os.getenv("PSE_CONFORMAL_ROOT", "artifacts/reports/conformal_real"),
        opportunity_root=opportunity_root
        or os.getenv("PSE_OPPORTUNITY_REPORT_ROOT", "artifacts/reports/opportunity_ablation_real"),
        historical_source_root=historical_source_root
        or os.getenv(
            "PSE_HISTORICAL_SOURCE_REPORT_ROOT",
            "artifacts/reports/historical_source_ablation_hardened",
        ),
    )

    def projections() -> pd.DataFrame:
        frame = _load_optional_table(projection_location)
        if frame.empty:
            raise HTTPException(
                status_code=503,
                detail=f"Projection artifact unavailable: {projection_location}",
            )
        return frame

    def trusted_board(
        snapshot: LeagueSnapshot, config: LeagueConfig, decision: DecisionType
    ) -> tuple[pd.DataFrame, dict[str, object]]:
        projection_frame = projections()
        trust = projection_metadata(
            projection_frame,
            projection_location,
            snapshot=snapshot,
        )
        coverage = identity_coverage(snapshot)
        board = build_decision_board(projection_frame, config, decision)
        board["data_mode"] = trust["data_mode"]
        board["model_version"] = trust["model_version"]
        board["projection_artifact_file_modified_at"] = trust[
            "projection_artifact_file_modified_at"
        ]
        board["missing_inputs"] = [list(trust["missing_inputs"]) for _ in range(len(board))]
        board["identity_coverage_rate"] = coverage["coverage_rate"]
        return board, {**trust, "identity_coverage": coverage}

    @app.get("/health")
    def health() -> dict[str, object]:
        projection_frame = _load_optional_table(projection_location)
        trust = (
            projection_metadata(projection_frame, projection_location)
            if not projection_frame.empty
            else {
                "data_mode": "UNAVAILABLE",
                "model_version": None,
                "projection_artifact_file_modified_at": None,
                "missing_inputs": ["projection_artifact"],
            }
        )
        return {
            "status": "ok",
            "version": "0.9.0",
            "projection_artifact": str(projection_location),
            "projection_available": Path(projection_location).exists(),
            "league_count": len(store.list()),
            **trust,
        }

    @app.get("/v1/leagues")
    def list_leagues() -> list[dict[str, object]]:
        return store.list()

    @app.post("/v1/integrations/sleeper/import")
    def import_sleeper(payload: dict[str, object]) -> dict[str, object]:
        league_id = str(payload.get("league_id") or "")
        if not league_id:
            raise HTTPException(status_code=422, detail="league_id is required")
        try:
            snapshot = SleeperImporter().import_league(
                league_id,
                external_user_id=(
                    str(payload.get("user_id")) if payload.get("user_id") else None
                ),
                include_free_agents=bool(payload.get("include_free_agents", True)),
                player_pool_limit=(
                    int(payload["player_pool_limit"])
                    if payload.get("player_pool_limit")
                    else None
                ),
            )
            path = store.save(snapshot)
            return {"league": snapshot.model_dump(mode="json"), "stored_at": str(path)}
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/v1/leagues/snapshot")
    def save_snapshot(snapshot: LeagueSnapshot) -> dict[str, str]:
        return {
            "stored_at": str(store.save(snapshot)),
            "league_id": snapshot.identity.league_id,
        }

    @app.get("/v1/leagues/{league_id}")
    def get_league(league_id: str) -> dict[str, object]:
        try:
            return store.load(league_id).model_dump(mode="json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/leagues/{league_id}/players")
    def league_players(
        league_id: str,
        decision: DecisionType = DecisionType.TRADE,
        free_agents_only: bool = False,
    ) -> list[dict[str, object]]:
        snapshot = store.load(league_id)
        config = _league_config(snapshot)
        board, _ = trusted_board(snapshot, config, decision)
        board = attach_ownership(board, snapshot)
        if free_agents_only:
            board = board.loc[board["is_free_agent"]]
        return frame_records(board)

    @app.get("/v1/leagues/{league_id}/power-rankings")
    def power_rankings(league_id: str) -> list[dict[str, object]]:
        snapshot = store.load(league_id)
        config = _league_config(snapshot)
        board, _ = trusted_board(snapshot, config, DecisionType.TRADE)
        return frame_records(league_power_rankings(snapshot, board))

    @app.get("/v1/leagues/{league_id}/needs")
    def league_needs(league_id: str) -> dict[str, object]:
        snapshot = store.load(league_id)
        config = _league_config(snapshot)
        board, trust = trusted_board(snapshot, config, DecisionType.TRADE)
        needs = roster_needs(snapshot, board)
        return {
            "data_mode": trust["data_mode"],
            "league_id": league_id,
            "model_version": trust["model_version"],
            "projection_artifact_file_modified_at": trust[
                "projection_artifact_file_modified_at"
            ],
            "identity_coverage": trust["identity_coverage"],
            "missing_inputs": trust["missing_inputs"],
            "needs": frame_records(needs),
        }

    @app.get("/v1/leagues/{league_id}/waivers")
    def waivers(league_id: str, roster_id: str = Query(...)) -> list[dict[str, object]]:
        snapshot = store.load(league_id)
        config = _league_config(snapshot)
        board, _ = trusted_board(snapshot, config, DecisionType.WAIVER)
        board = attach_ownership(board, snapshot)
        candidates = board.loc[board["is_free_agent"]]
        roster = board.loc[board["owner_roster_id"].eq(roster_id)]
        ranked = rank_waiver_candidates(candidates, roster, faab_budget=config.faab_budget)
        return frame_records(ranked.head(100))

    @app.get("/v1/leagues/{league_id}/lineup")
    def lineup(league_id: str, roster_id: str = Query(...)) -> list[dict[str, object]]:
        snapshot = store.load(league_id)
        config = _league_config(snapshot)
        board, _ = trusted_board(snapshot, config, DecisionType.START_SIT)
        board = attach_ownership(board, snapshot)
        roster = board.loc[board["owner_roster_id"].eq(roster_id)].copy()
        roster["lineup_score"] = roster["decision_specific_score"]
        return frame_records(optimize_lineup(roster, config))

    @app.post("/v1/trades/analyze")
    def trade_analyze(request: TradeAnalysisRequest) -> dict[str, object]:
        try:
            snapshot = store.load(request.league_id)
            config = _league_config(snapshot)
            trade_board, _ = trusted_board(snapshot, config, DecisionType.TRADE)
            result = analyze_trade(snapshot, trade_board, request, config)
            return result.model_dump(mode="json")
        except (FileNotFoundError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/leagues/{league_id}/trades/suggestions")
    def trade_suggestions(
        league_id: str,
        roster_id: str = Query(...),
        limit: int = Query(12, ge=1, le=50),
    ) -> list[dict[str, object]]:
        snapshot = store.load(league_id)
        config = _league_config(snapshot)
        trade_board, _ = trusted_board(snapshot, config, DecisionType.TRADE)
        results = suggest_trades(
            snapshot,
            trade_board,
            config,
            roster_id=roster_id,
            max_suggestions=limit,
        )
        return [result.model_dump(mode="json") for result in results]

    @app.get("/v1/nfl/state")
    def nfl_state(season: int, through_week: int | None = None) -> dict[str, object]:
        valid_schedule_modes = {
            "LIVE_OFFICIAL",
            "HISTORICAL_BACKTEST",
            "SYNTHETIC_DEMO",
        }
        if schedule_mode not in valid_schedule_modes:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Schedule provenance mode {schedule_mode!r} is not trusted. "
                    "Set PSE_SCHEDULES_DATA_MODE to "
                    "LIVE_OFFICIAL, HISTORICAL_BACKTEST, or SYNTHETIC_DEMO."
                ),
            )
        schedules = _load_optional_table(schedule_location)
        if schedules.empty:
            raise HTTPException(
                status_code=503,
                detail=f"Schedule artifact unavailable: {schedule_location}",
            )
        return {
            "data_mode": schedule_mode,
            **build_nfl_state(schedules, season, through_week).model_dump(mode="json"),
        }

    @app.get("/v1/nfl/team-context")
    def nfl_team_context(
        season: int | None = None,
        week: int | None = None,
        team: str | None = None,
        limit: int = Query(1000, ge=1, le=5000),
    ) -> dict[str, object]:
        try:
            return team_context_response(
                team_context_location,
                season=season,
                week=week,
                team=team,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/research/summary")
    def research_summary() -> dict[str, object]:
        return research.summary()

    @app.get("/v1/research/predictions")
    def research_predictions(
        source: str = Query("benchmark", pattern="^(benchmark|frozen_opportunity)$"),
        target: str = Query("fantasy_points_ppr", pattern="^[a-z0-9_]+$"),
        season: int | None = None,
        week: int | None = Query(None, ge=1, le=25),
        position: str | None = Query(
            None, pattern="^(QB|RB|WR|TE|qb|rb|wr|te)$"
        ),
        method: str | None = None,
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict[str, object]:
        try:
            return research.predictions(
                source=source,  # type: ignore[arg-type]
                target=target,
                season=season,
                week=week,
                position=position,
                method=method,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/copilot/context/{league_id}")
    def copilot_context(
        league_id: str, roster_id: str | None = None
    ) -> dict[str, object]:
        snapshot = store.load(league_id)
        config = _league_config(snapshot)
        board, trust = trusted_board(snapshot, config, DecisionType.TRADE)
        board = attach_ownership(board, snapshot)
        response: dict[str, object] = {
            "league": snapshot.model_dump(mode="json"),
            "trust": trust,
            "power_rankings": frame_records(
                league_power_rankings(snapshot, board).head(12)
            ),
            "top_free_agents": frame_records(
                board.loc[board["is_free_agent"]].head(20)
            ),
        }
        if roster_id:
            response["roster_players"] = frame_records(
                board.loc[board["owner_roster_id"].eq(roster_id)]
            )
        return response

    return app


app = create_app()
