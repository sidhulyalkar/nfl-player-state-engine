from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from player_state_engine.api.draft_routes import DraftBoardService, DraftCompareRequest
from player_state_engine.fantasy.draft import DraftState
from player_state_engine.fantasy.draft_survival import DraftSurvivalArtifact
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.integrations.portfolio import league_config_from_snapshot
from player_state_engine.product.live_adp import (
    DEFAULT_LIVE_ADP_ROOT,
    attach_live_adp,
    live_adp_status,
    load_live_adp_snapshot,
    refresh_fantasypros_adp_snapshot,
)
from player_state_engine.product.schemas import LeagueSnapshot

try:
    from fastapi import FastAPI, HTTPException, Query
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


class MarketAwareDraftBoardService(DraftBoardService):
    """Production Draft Room composition with a separately refreshed ADP timing overlay.

    Football projections remain byte-identical to the verified champion. The market overlay is
    attached to an in-memory copy immediately before live draft scoring, so refreshing ADP cannot
    mutate artifact authority or leak into non-draft decision surfaces.
    """

    def __init__(
        self,
        *,
        market_root: str | Path | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.market_root = Path(
            market_root or os.getenv("PSE_LIVE_ADP_ROOT", str(DEFAULT_LIVE_ADP_ROOT))
        )

    def _market_projection_view(
        self,
        projections: pd.DataFrame,
        config: LeagueConfig,
    ) -> tuple[pd.DataFrame, dict[str, object]]:
        market, metadata = load_live_adp_snapshot(self.market_root)
        view, status = attach_live_adp(projections, config, market, metadata)
        status["snapshot_status"] = live_adp_status(self.market_root)
        return view, status

    def _live_board(
        self,
        snapshot: LeagueSnapshot,
        projections: pd.DataFrame,
        config: LeagueConfig,
        state: DraftState,
        picks: list[dict[str, object]],
    ) -> tuple[pd.DataFrame, DraftSurvivalArtifact | None, dict[str, int]]:
        market_view, _status = self._market_projection_view(projections, config)
        return super()._live_board(snapshot, market_view, config, state, picks)

    def _market_status_for_league(self, league_id: str) -> dict[str, object]:
        try:
            snapshot = self.load_snapshot(league_id)
        except FileNotFoundError:
            return {**live_adp_status(self.market_root), "league_available": False}
        projections = self._load_projections()
        config = league_config_from_snapshot(snapshot)
        _view, status = self._market_projection_view(projections, config)
        status["league_available"] = True
        status["league_id"] = snapshot.identity.league_id
        status["league_name"] = snapshot.identity.name
        status["platform"] = snapshot.identity.platform
        return status

    def board(self, league_id: str, roster_id: str, **kwargs) -> dict[str, object]:
        result = super().board(league_id, roster_id, **kwargs)
        result["draft_market"] = self._market_status_for_league(league_id)
        return result

    def compare(self, league_id: str, request: DraftCompareRequest) -> dict[str, object]:
        result = super().compare(league_id, request)
        result["draft_market"] = self._market_status_for_league(league_id)
        return result

    def refresh_market(self, season: int) -> dict[str, object]:
        return refresh_fantasypros_adp_snapshot(int(season), root=self.market_root)

    def market_status(self) -> dict[str, object]:
        return live_adp_status(self.market_root)


def install_market_draft_routes(
    app: FastAPI,
    *,
    store_root: str | Path | None = None,
    projections_path: str | Path | None = None,
    market_root: str | Path | None = None,
) -> MarketAwareDraftBoardService:
    """Install the production Draft Room with current-market timing as an external overlay."""

    service = MarketAwareDraftBoardService(
        store_root=store_root,
        projections_path=projections_path,
        market_root=market_root,
    )

    @app.get("/v1/draft/leagues")
    def draft_leagues() -> list[dict[str, object]]:
        return service.list_leagues()

    @app.get("/v1/draft/market/status")
    def draft_market_status() -> dict[str, object]:
        return service.market_status()

    @app.post("/v1/draft/market/refresh")
    def refresh_draft_market(season: int = Query(default=2026, ge=2012, le=2100)) -> dict[str, object]:
        try:
            return service.refresh_market(season)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - external API failures must not crash the Product API.
            raise HTTPException(
                status_code=502,
                detail=f"FantasyPros ADP refresh failed; preserved previous market snapshot: {exc}",
            ) from exc

    @app.get("/v1/leagues/{league_id}/draft/market")
    def league_draft_market(league_id: str) -> dict[str, object]:
        return service._market_status_for_league(league_id)

    @app.get("/v1/leagues/{league_id}/draft/board")
    def live_draft_board(
        league_id: str,
        roster_id: str = Query(...),
        draft_slot: int | None = Query(default=None, ge=1),
        total_rounds: int | None = Query(default=None, ge=1),
        refresh: bool = True,
        force_refresh: bool = False,
        limit: int = Query(default=250, ge=1, le=1000),
    ) -> dict[str, object]:
        try:
            return service.board(
                league_id,
                roster_id,
                draft_slot=draft_slot,
                total_rounds=total_rounds,
                refresh=refresh,
                force_refresh=force_refresh,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/leagues/{league_id}/draft/compare")
    def compare_draft_candidates(
        league_id: str, request: DraftCompareRequest
    ) -> dict[str, object]:
        try:
            return service.compare(league_id, request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return service
