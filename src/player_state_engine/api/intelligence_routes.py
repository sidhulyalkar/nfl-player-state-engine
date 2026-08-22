from __future__ import annotations

import os
from pathlib import Path

from player_state_engine.data.io import read_table
from player_state_engine.integrations.portfolio import league_config_from_snapshot
from player_state_engine.product.intelligence import build_player_intelligence
from player_state_engine.product.provenance import projection_metadata
from player_state_engine.product.research import ResearchArtifacts
from player_state_engine.product.store import LeagueSnapshotStore

try:
    from fastapi import FastAPI, HTTPException, Query
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


def install_intelligence_routes(
    app: FastAPI,
    *,
    store_root: str | Path | None = None,
    projections_path: str | Path | None = None,
    benchmark_root: str | Path | None = None,
    conformal_root: str | Path | None = None,
    opportunity_root: str | Path | None = None,
    historical_source_root: str | Path | None = None,
) -> None:
    """Expose model data as read-only product contracts without duplicating model logic in React."""

    store = LeagueSnapshotStore(
        store_root or os.getenv("PSE_LEAGUE_STORE", "data/product/leagues")
    )
    projection_location = Path(
        projections_path
        or os.getenv("PSE_PROJECTIONS_PATH", "artifacts/predictions/product_player_values.csv")
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

    def projections():
        if not projection_location.is_file():
            raise FileNotFoundError(f"Projection artifact unavailable: {projection_location}")
        return read_table(projection_location)

    @app.get("/v1/leagues/{league_id}/players/{player_id}/intelligence")
    def player_intelligence(league_id: str, player_id: str) -> dict[str, object]:
        try:
            snapshot = store.load(league_id)
            frame = projections()
            config = league_config_from_snapshot(snapshot)
            if snapshot.settings.faab_budget is not None:
                config.faab_budget = float(snapshot.settings.faab_budget)
            if snapshot.settings.playoff_week_start is not None:
                config.playoff_weeks = tuple(range(int(snapshot.settings.playoff_week_start), 18))
            trust = projection_metadata(frame, projection_location, snapshot=snapshot)
            return build_player_intelligence(
                frame,
                config,
                snapshot,
                player_id,
                trust=trust,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/research/diagnostics")
    def research_diagnostics(
        target: str = Query("fantasy_points_ppr", pattern="^[a-z0-9_]+$"),
        method: str = Query("quantile_engine", pattern="^[a-zA-Z0-9_.-]+$"),
        minimum_rows: int = Query(20, ge=5, le=5000),
    ) -> dict[str, object]:
        try:
            return research.diagnostics(
                target=target,
                method=method,
                minimum_rows=minimum_rows,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/research/players/{player_id}/history")
    def research_player_history(
        player_id: str,
        target: str = Query("fantasy_points_ppr", pattern="^[a-z0-9_]+$"),
        method: str = Query("quantile_engine", pattern="^[a-zA-Z0-9_.-]+$"),
        limit: int = Query(200, ge=1, le=2000),
    ) -> dict[str, object]:
        try:
            return research.predictions(
                source="benchmark",
                target=target,
                player_id=player_id,
                method=method,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/model/observatory")
    def model_observatory(
        target: str = Query("fantasy_points_ppr", pattern="^[a-z0-9_]+$"),
        method: str = Query("quantile_engine", pattern="^[a-zA-Z0-9_.-]+$"),
    ) -> dict[str, object]:
        summary = research.summary()
        try:
            diagnostics = research.diagnostics(target=target, method=method)
        except (FileNotFoundError, ValueError) as exc:
            diagnostics = {
                "data_mode": "UNAVAILABLE",
                "authority": "diagnostic_only",
                "target": target,
                "method": method,
                "error": str(exc),
                "overall": {},
                "by_position": [],
                "by_season": [],
                "by_position_season": [],
            }
        artifacts = summary.get("artifacts", {})
        available = sum(
            bool(metadata.get("available"))
            for metadata in artifacts.values()
            if isinstance(metadata, dict)
        )
        total = len(artifacts) if isinstance(artifacts, dict) else 0
        return {
            "data_mode": "RESEARCH",
            "authority": {
                "production_champion": "direct_player_quantile_model",
                "player_state_graph": "research_challenger",
                "diagnostics": "historical_backtest_only",
                "promotion_is_automatic": False,
            },
            "artifact_health": {
                "available": available,
                "total": total,
                "missing": list(summary.get("missing_inputs", [])),
                "latest_file_modified_at": summary.get("artifact_file_modified_at"),
            },
            "diagnostics": diagnostics,
            "benchmark": summary.get("benchmark", []),
            "conformal": summary.get("conformal", []),
            "frozen_opportunity": summary.get("frozen_opportunity", []),
            "historical_sources": summary.get("historical_sources", []),
            "historical_source_coverage": summary.get("historical_source_coverage", []),
        }
