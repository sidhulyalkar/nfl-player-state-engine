from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from player_state_engine.data.io import read_table
from player_state_engine.fantasy.decision_board import DecisionType, build_decision_board
from player_state_engine.fantasy.decisions import optimize_lineup, rank_waiver_candidates
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.integrations.sleeper import SleeperImporter
from player_state_engine.product.league_picture import attach_ownership, league_power_rankings
from player_state_engine.product.nfl_state import build_nfl_state
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
    slots: dict[str, int] = {
        "QB": 0,
        "RB": 0,
        "WR": 0,
        "TE": 0,
        "FLEX": 0,
        "SUPERFLEX": 0,
        "BENCH": 0,
    }
    slot_map = {
        "QB": "QB",
        "RB": "RB",
        "WR": "WR",
        "TE": "TE",
        "FLEX": "FLEX",
        "SUPER_FLEX": "SUPERFLEX",
        "SUPERFLEX": "SUPERFLEX",
        "BN": "BENCH",
        "BENCH": "BENCH",
    }
    for slot in snapshot.settings.roster_positions:
        mapped = slot_map.get(slot)
        if mapped:
            slots[mapped] = slots.get(mapped, 0) + 1
    if not any(slots[position] for position in ("QB", "RB", "WR", "TE")):
        slots.update({"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6})
    scoring = "ppr" if snapshot.settings.scoring.get("rec", 1.0) >= 0.75 else "half_ppr"
    return LeagueConfig(
        teams=snapshot.settings.teams,
        scoring=scoring,
        roster_slots=slots,
        faab_budget=snapshot.settings.faab_budget or 100.0,
        playoff_weeks=tuple(range(snapshot.settings.playoff_week_start or 15, 18)),
    )


def create_app(
    *,
    store_root: str | Path | None = None,
    projections_path: str | Path | None = None,
    schedules_path: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(
        title="NFL Player State Engine Product API",
        version="0.6.0",
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
    store = LeagueSnapshotStore(store_root or os.getenv("PSE_LEAGUE_STORE", "data/product/leagues"))
    projection_location = projections_path or os.getenv(
        "PSE_PROJECTIONS_PATH", "artifacts/predictions/product_player_values.csv"
    )
    schedule_location = schedules_path or os.getenv(
        "PSE_SCHEDULES_PATH", "data/raw/nflverse/schedules.csv"
    )

    def projections() -> pd.DataFrame:
        frame = _load_optional_table(projection_location)
        if frame.empty:
            raise HTTPException(
                status_code=503, detail=f"Projection artifact unavailable: {projection_location}"
            )
        return frame

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "version": "0.6.0",
            "projection_artifact": str(projection_location),
            "projection_available": Path(projection_location).exists(),
            "league_count": len(store.list()),
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
                external_user_id=str(payload.get("user_id")) if payload.get("user_id") else None,
                include_free_agents=bool(payload.get("include_free_agents", True)),
                player_pool_limit=int(payload["player_pool_limit"])
                if payload.get("player_pool_limit")
                else None,
            )
            path = store.save(snapshot)
            return {"league": snapshot.model_dump(mode="json"), "stored_at": str(path)}
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/v1/leagues/snapshot")
    def save_snapshot(snapshot: LeagueSnapshot) -> dict[str, str]:
        return {"stored_at": str(store.save(snapshot)), "league_id": snapshot.identity.league_id}

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
        board = build_decision_board(projections(), config, decision)
        board = attach_ownership(board, snapshot)
        if free_agents_only:
            board = board.loc[board["is_free_agent"]]
        return board.replace({float("nan"): None}).to_dict(orient="records")

    @app.get("/v1/leagues/{league_id}/power-rankings")
    def power_rankings(league_id: str) -> list[dict[str, object]]:
        snapshot = store.load(league_id)
        config = _league_config(snapshot)
        board = build_decision_board(projections(), config, DecisionType.TRADE)
        return (
            league_power_rankings(snapshot, board)
            .replace({float("nan"): None})
            .to_dict(orient="records")
        )

    @app.get("/v1/leagues/{league_id}/waivers")
    def waivers(league_id: str, roster_id: str = Query(...)) -> list[dict[str, object]]:
        snapshot = store.load(league_id)
        config = _league_config(snapshot)
        board = attach_ownership(
            build_decision_board(projections(), config, DecisionType.WAIVER), snapshot
        )
        candidates = board.loc[board["is_free_agent"]]
        roster = board.loc[board["owner_roster_id"].eq(roster_id)]
        ranked = rank_waiver_candidates(candidates, roster, faab_budget=config.faab_budget)
        return ranked.head(100).replace({float("nan"): None}).to_dict(orient="records")

    @app.get("/v1/leagues/{league_id}/lineup")
    def lineup(league_id: str, roster_id: str = Query(...)) -> list[dict[str, object]]:
        snapshot = store.load(league_id)
        config = _league_config(snapshot)
        board = attach_ownership(
            build_decision_board(projections(), config, DecisionType.START_SIT), snapshot
        )
        roster = board.loc[board["owner_roster_id"].eq(roster_id)].copy()
        roster["lineup_score"] = roster["decision_specific_score"]
        return (
            optimize_lineup(roster, config).replace({float("nan"): None}).to_dict(orient="records")
        )

    @app.post("/v1/trades/analyze")
    def trade_analyze(request: TradeAnalysisRequest) -> dict[str, object]:
        try:
            snapshot = store.load(request.league_id)
            config = _league_config(snapshot)
            trade_board = build_decision_board(projections(), config, DecisionType.TRADE)
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
        trade_board = build_decision_board(projections(), config, DecisionType.TRADE)
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
        schedules = _load_optional_table(schedule_location)
        if schedules.empty:
            raise HTTPException(
                status_code=503, detail=f"Schedule artifact unavailable: {schedule_location}"
            )
        return build_nfl_state(schedules, season, through_week).model_dump(mode="json")

    @app.get("/v1/copilot/context/{league_id}")
    def copilot_context(league_id: str, roster_id: str | None = None) -> dict[str, object]:
        snapshot = store.load(league_id)
        config = _league_config(snapshot)
        board = attach_ownership(
            build_decision_board(projections(), config, DecisionType.TRADE), snapshot
        )
        response: dict[str, object] = {
            "league": snapshot.model_dump(mode="json"),
            "power_rankings": league_power_rankings(snapshot, board)
            .head(12)
            .to_dict(orient="records"),
            "top_free_agents": board.loc[board["is_free_agent"]].head(20).to_dict(orient="records"),
        }
        if roster_id:
            response["roster_players"] = board.loc[board["owner_roster_id"].eq(roster_id)].to_dict(
                orient="records"
            )
        return response

    return app


app = create_app()
