from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from player_state_engine import __version__
from player_state_engine.api.app import create_app as create_base_app
from player_state_engine.api.draft_day_doctor_routes import install_draft_day_doctor_routes
from player_state_engine.api.draft_launch_routes import install_draft_launch_routes
from player_state_engine.api.draft_planner_routes import install_draft_planner_routes
from player_state_engine.api.draft_reliability_routes import install_draft_reliability_routes
from player_state_engine.api.evidence_routes import install_evidence_routes
from player_state_engine.api.game_intelligence_routes import install_game_intelligence_routes
from player_state_engine.api.intelligence_routes import install_intelligence_routes
from player_state_engine.api.league_connection_routes import install_league_connection_routes
from player_state_engine.api.market_draft_routes import install_market_draft_routes
from player_state_engine.api.nfl_hub_routes import install_nfl_hub_routes
from player_state_engine.api.ranking_routes import install_ranking_routes
from player_state_engine.api.shadow_season_routes import install_shadow_season_routes
from player_state_engine.api.showcase_routes import install_showcase_routes
from player_state_engine.api.structured_intelligence_routes import (
    install_structured_intelligence_routes,
)
from player_state_engine.product.projection_artifact_source import ProjectionArtifactSource


def _projection_failure(exc: Exception, *, source_mode: str) -> dict[str, object]:
    detail = (
        "Verified production projection champion is unavailable."
        if source_mode == "champion"
        else "Configured development projection artifact is unavailable."
    )
    return {
        "detail": detail,
        "projection_source_mode": source_mode,
        "projection_integrity_verified": False,
        "projection_error": str(exc),
    }


def _replace_health_version(app: FastAPI) -> None:
    """Keep inherited health diagnostics while making package and artifact identity authoritative."""

    inherited: Callable[[], dict[str, object]] | None = None
    for route in list(app.router.routes):
        if getattr(route, "path", None) != "/health":
            continue
        methods = getattr(route, "methods", set()) or set()
        if "GET" not in methods:
            continue
        inherited = getattr(route, "endpoint", None)
        app.router.routes.remove(route)
        break

    @app.get("/health")
    def operational_health() -> dict[str, object]:
        payload = dict(inherited()) if inherited is not None else {"status": "ok"}
        payload["version"] = __version__
        source = getattr(app.state, "projection_artifact_source", None)
        if source is None:
            return payload
        try:
            snapshot = source.load()
        except (OSError, KeyError, ValueError, PermissionError, RuntimeError) as exc:
            payload.update(_projection_failure(exc, source_mode=source.mode))
            payload["status"] = "degraded"
            return payload
        payload.update(snapshot.trust_metadata())
        draft_service = getattr(app.state, "draft_service", None)
        if draft_service is not None and hasattr(draft_service, "market_status"):
            payload["draft_market"] = draft_service.market_status()
        return payload


def _install_projection_integrity_guard(
    app: FastAPI,
    source: ProjectionArtifactSource,
    *,
    initial_bundle_id: str | None,
    initial_path: str,
) -> None:
    """Re-verify champion bytes before serving production decision surfaces.

    Services are installed against one exact resolved path. If a champion pointer changes while
    the process is running, fail closed and require a restart so every route is rebuilt around one
    coherent artifact identity rather than mixing old service state with a new champion.

    Frozen showcase routes are deliberately exempt: they are evaluation-only artifacts with an
    explicit no-decision-authority contract and remain inspectable even if the live champion is
    unavailable or undergoing operator repair.
    """

    if source.mode != "champion":
        return

    @app.middleware("http")
    async def verified_projection_guard(request: Request, call_next: Callable[..., Any]):
        path = request.url.path
        if (
            path == "/health"
            or path.startswith("/docs")
            or path.startswith("/openapi")
            or path.startswith("/v1/model/showcase")
        ):
            return await call_next(request)
        try:
            snapshot = source.load()
            if snapshot.bundle_id != initial_bundle_id or str(snapshot.path) != initial_path:
                raise RuntimeError(
                    "Projection champion changed after process start; restart is required before serving it."
                )
        except (OSError, KeyError, ValueError, PermissionError, RuntimeError) as exc:
            return JSONResponse(
                status_code=503,
                content=_projection_failure(exc, source_mode=source.mode),
            )
        return await call_next(request)


def create_app(**kwargs: Any) -> FastAPI:
    """Create the operational Product API plus guarded research challenger surfaces."""
    operational_only = {
        "ranking_root",
        "game_intelligence_root",
        "game_intelligence_registry",
        "game_intelligence_benchmark_root",
        "player_state_graph_root",
        "live_store_root",
        "evidence_factory_root",
        "shadow_season_root",
        "structured_intelligence_root",
        "intelligence_activation_registry",
        "nfl_hub_root",
        "nfl_hub_projections_path",
        "live_adp_root",
        "special_teams_market_path",
        "league_portfolio_path",
        "model_showcase_root",
    }
    base_kwargs = {key: value for key, value in kwargs.items() if key not in operational_only}

    projection_source = ProjectionArtifactSource.from_environment(
        explicit_path=kwargs.get("projections_path")
    )
    initial_projection = None
    if projection_source.mode == "champion":
        # Champion mode is an explicit production contract. Refuse to construct a product API
        # around an unresolved or unverified champion rather than falling back to a path.
        initial_projection = projection_source.load()
        resolved_projections_path = str(initial_projection.path)
    else:
        resolved_projections_path = str(projection_source.path)
    base_kwargs["projections_path"] = resolved_projections_path

    app = create_base_app(**base_kwargs)
    app.state.projection_artifact_source = projection_source
    app.state.initial_projection_bundle_id = (
        initial_projection.bundle_id if initial_projection is not None else None
    )

    draft_service = install_market_draft_routes(
        app,
        store_root=kwargs.get("store_root"),
        projections_path=resolved_projections_path,
        market_root=kwargs.get("live_adp_root"),
    )
    app.state.draft_service = draft_service
    connection_service = install_league_connection_routes(
        app,
        draft_service=draft_service,
        portfolio_path=kwargs.get("league_portfolio_path"),
    )
    app.state.league_connection_service = connection_service
    doctor_service = install_draft_day_doctor_routes(
        app,
        projection_source=projection_source,
        draft_service=draft_service,
        nfl_hub_root=kwargs.get("nfl_hub_root"),
        special_teams_path=kwargs.get("special_teams_market_path"),
        portfolio_path=kwargs.get("league_portfolio_path"),
    )
    app.state.draft_day_doctor = doctor_service
    launch_service = install_draft_launch_routes(
        app,
        draft_service=draft_service,
        connection_service=connection_service,
        doctor_service=doctor_service,
        nfl_hub_root=kwargs.get("nfl_hub_root"),
        nfl_hub_projections_path=kwargs.get("nfl_hub_projections_path"),
        special_teams_path=kwargs.get("special_teams_market_path"),
    )
    app.state.draft_launch_control = launch_service
    install_draft_planner_routes(app, draft_service)
    install_draft_reliability_routes(app, draft_service)
    install_intelligence_routes(
        app,
        store_root=kwargs.get("store_root"),
        live_store_root=kwargs.get("live_store_root"),
        projections_path=resolved_projections_path,
        benchmark_root=kwargs.get("benchmark_root"),
        conformal_root=kwargs.get("conformal_root"),
        opportunity_root=kwargs.get("opportunity_root"),
        historical_source_root=kwargs.get("historical_source_root"),
        player_state_graph_root=kwargs.get("player_state_graph_root"),
    )
    install_nfl_hub_routes(
        app,
        root=kwargs.get("nfl_hub_root"),
        projections_path=kwargs.get("nfl_hub_projections_path"),
    )
    install_evidence_routes(
        app,
        evidence_factory_root=kwargs.get("evidence_factory_root"),
    )
    install_shadow_season_routes(
        app,
        artifact_root=kwargs.get("shadow_season_root"),
    )
    install_structured_intelligence_routes(
        app,
        artifact_root=kwargs.get("structured_intelligence_root"),
        activation_registry_path=kwargs.get("intelligence_activation_registry"),
    )
    install_ranking_routes(
        app,
        store_root=kwargs.get("store_root"),
        projections_path=resolved_projections_path,
        ranking_root=kwargs.get("ranking_root"),
    )
    install_game_intelligence_routes(
        app,
        artifact_root=kwargs.get("game_intelligence_root"),
        registry_path=kwargs.get("game_intelligence_registry"),
        benchmark_root=kwargs.get("game_intelligence_benchmark_root"),
    )
    app.state.model_showcase = install_showcase_routes(
        app,
        root=kwargs.get("model_showcase_root"),
    )
    _install_projection_integrity_guard(
        app,
        projection_source,
        initial_bundle_id=(initial_projection.bundle_id if initial_projection is not None else None),
        initial_path=resolved_projections_path,
    )
    app.version = __version__
    _replace_health_version(app)
    app.description = (
        f"{app.description} Live Draft War Room with current-state-only launch control, explicit "
        "real-league onboarding, a fail-closed portfolio-aware draft-day doctor, point-in-time "
        "external ADP timing, NFL Hub state-change intelligence, player intelligence, cross-league "
        "portfolio exposure, Player State Graph shadow comparison and sensitivity, frozen Evidence "
        "Factory, immutable 2026 live shadow-season evidence, structured intelligence evidence "
        "ledger, model observatory, read-only weekly model-versus-expert showcase evidence, ranking "
        "calibration, guarded draft reliability, guarded game-intelligence simulation, expanding "
        "frozen replay, factorial attribution, simulated-state opportunity, drive-volume, "
        "possession-transition, fourth-down decision, and terminal-family research surfaces."
    )
    return app


app = create_app()
