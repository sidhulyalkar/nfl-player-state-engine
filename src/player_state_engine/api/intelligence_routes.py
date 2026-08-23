from __future__ import annotations

import json
import os
from pathlib import Path

from player_state_engine.data.io import read_table
from player_state_engine.fantasy.decision_board import DecisionType, build_decision_board
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.integrations.portfolio import league_config_from_snapshot
from player_state_engine.product.intelligence import build_player_intelligence
from player_state_engine.product.league_picture import attach_ownership
from player_state_engine.product.portfolio_exposure import build_portfolio_exposure
from player_state_engine.product.provenance import frame_records, projection_metadata
from player_state_engine.product.research import ResearchArtifacts
from player_state_engine.product.schemas import LeagueSnapshot
from player_state_engine.product.shadow_lab import (
    ScenarioControls,
    StateGraphArtifactStore,
    evaluate_shadow_replay,
)
from player_state_engine.product.store import LeagueSnapshotStore

try:
    from fastapi import FastAPI, HTTPException, Query
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


def install_intelligence_routes(
    app: FastAPI,
    *,
    store_root: str | Path | None = None,
    live_store_root: str | Path | None = None,
    projections_path: str | Path | None = None,
    benchmark_root: str | Path | None = None,
    conformal_root: str | Path | None = None,
    opportunity_root: str | Path | None = None,
    historical_source_root: str | Path | None = None,
    player_state_graph_root: str | Path | None = None,
) -> None:
    """Expose model data as read-only product contracts without duplicating model logic in React."""

    store = LeagueSnapshotStore(
        store_root or os.getenv("PSE_LEAGUE_STORE", "data/product/leagues")
    )
    live_store = LeagueSnapshotStore(
        live_store_root
        or os.getenv("PSE_LIVE_LEAGUE_STORE", "data/product/live_leagues")
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
    graph = StateGraphArtifactStore(
        player_state_graph_root
        or os.getenv("PSE_PLAYER_STATE_GRAPH_ROOT", "artifacts/player_state_graph")
    )

    def projections():
        if not projection_location.is_file():
            raise FileNotFoundError(f"Projection artifact unavailable: {projection_location}")
        return read_table(projection_location)

    def all_snapshots() -> list[LeagueSnapshot]:
        by_key: dict[str, LeagueSnapshot] = {}
        for snapshot_store in (store, live_store):
            for snapshot in snapshot_store.iter_snapshots():
                by_key[snapshot.identity.canonical_key] = snapshot
        return list(by_key.values())

    def load_snapshot(league_id: str) -> LeagueSnapshot:
        try:
            return store.find(league_id)
        except FileNotFoundError:
            return live_store.find(league_id)

    def league_context(
        league_id: str,
    ) -> tuple[LeagueSnapshot, object, LeagueConfig, dict[str, object]]:
        snapshot = load_snapshot(league_id)
        frame = projections()
        config = league_config_from_snapshot(snapshot)
        if snapshot.settings.faab_budget is not None:
            config.faab_budget = float(snapshot.settings.faab_budget)
        if snapshot.settings.playoff_week_start is not None:
            config.playoff_weeks = tuple(range(int(snapshot.settings.playoff_week_start), 18))
        trust = projection_metadata(frame, projection_location, snapshot=snapshot)
        return snapshot, frame, config, trust

    def player_contract(league_id: str, player_id: str) -> tuple[dict[str, object], LeagueConfig]:
        snapshot, frame, config, trust = league_context(league_id)
        return (
            build_player_intelligence(
                frame,
                config,
                snapshot,
                player_id,
                trust=trust,
            ),
            config,
        )

    def graph_manifest() -> dict[str, object] | None:
        path = graph.root / "run_manifest.json"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def graph_contract_status(config: LeagueConfig) -> dict[str, object]:
        manifest = graph_manifest()
        if manifest is None:
            return {
                "comparable": False,
                "status": "legacy_or_missing_manifest",
                "note": "Graph scoring contract cannot be verified for this artifact.",
            }
        contract = manifest.get("league_contract")
        if not isinstance(contract, dict):
            return {
                "comparable": False,
                "status": "manifest_contract_missing",
                "note": "Graph manifest does not contain a league contract.",
            }
        graph_weights = contract.get("scoring_weights")
        if not isinstance(graph_weights, dict):
            return {
                "comparable": False,
                "status": "manifest_scoring_missing",
                "note": "Graph scoring weights are unavailable.",
            }
        current = {str(key): float(value) for key, value in config.scoring_weights.items()}
        candidate = {str(key): float(value) for key, value in graph_weights.items()}
        scoring_match = current == candidate
        return {
            "comparable": scoring_match,
            "status": "exact_scoring_match" if scoring_match else "scoring_contract_mismatch",
            "graph_contract": contract,
            "note": (
                "The challenger and production distributions use the same scoring weights."
                if scoring_match
                else "Raw challenger values are visible for research, but they are not decision-comparable under this league scoring contract."
            ),
        }

    def weekly_projection(contract: dict[str, object]) -> dict[str, float | None]:
        raw = contract.get("raw_model_fields")
        row = raw if isinstance(raw, dict) else {}

        def first(*names: str) -> float | None:
            for name in names:
                value = row.get(name)
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                if numeric == numeric and abs(numeric) != float("inf"):
                    return numeric
            return None

        return {
            "q10": first("week_points_q10", "fantasy_points_ppr_q10"),
            "q50": first("week_points_q50", "fantasy_points_ppr_q50"),
            "q90": first("week_points_q90", "fantasy_points_ppr_q90"),
        }

    def shadow_evaluation_payload() -> dict[str, object]:
        manifest = graph_manifest()
        if manifest is None:
            return {
                "data_mode": "UNAVAILABLE",
                "authority": "research_shadow_only",
                "reason": "player_state_graph_run_manifest_unavailable",
            }
        contract = manifest.get("league_contract")
        ppr = LeagueConfig(scoring="ppr")
        graph_weights = contract.get("scoring_weights") if isinstance(contract, dict) else None
        if not isinstance(graph_weights, dict) or {
            str(key): float(value) for key, value in graph_weights.items()
        } != {str(key): float(value) for key, value in ppr.scoring_weights.items()}:
            return {
                "data_mode": "UNAVAILABLE",
                "authority": "research_shadow_only",
                "reason": "graph_scoring_contract_not_comparable_to_ppr_champion",
                "graph_contract": contract,
            }
        champion_path = (
            research.benchmark_root
            / "fantasy_points_ppr"
            / "fantasy_points_ppr_predictions.csv"
        )
        if not champion_path.is_file() or not graph.summary_path.is_file():
            return {
                "data_mode": "UNAVAILABLE",
                "authority": "research_shadow_only",
                "reason": "paired_champion_or_challenger_artifact_unavailable",
                "champion_available": champion_path.is_file(),
                "challenger_available": graph.summary_path.is_file(),
            }
        champion = read_table(champion_path)
        if "method" in champion:
            champion = champion.loc[
                champion["method"].astype(str).eq("quantile_engine")
            ].copy()
        try:
            return evaluate_shadow_replay(champion, read_table(graph.summary_path))
        except ValueError as exc:
            return {
                "data_mode": "UNAVAILABLE",
                "authority": "research_shadow_only",
                "reason": str(exc),
            }

    @app.get("/v1/intelligence/leagues")
    def intelligence_leagues() -> list[dict[str, object]]:
        snapshots = sorted(
            all_snapshots(),
            key=lambda snapshot: (snapshot.identity.name.lower(), snapshot.identity.league_id),
        )
        return [
            {
                "league_id": snapshot.identity.league_id,
                "name": snapshot.identity.name,
                "platform": snapshot.identity.platform,
                "season": snapshot.identity.season,
                "imported_at": snapshot.identity.imported_at.isoformat(),
                "external_roster_id": snapshot.metadata.get("external_roster_id"),
            }
            for snapshot in snapshots
        ]

    @app.get("/v1/leagues/{league_id}/intelligence/players")
    def intelligence_players(
        league_id: str,
        decision: DecisionType = DecisionType.TRADE,
    ) -> list[dict[str, object]]:
        try:
            snapshot, frame, config, trust = league_context(league_id)
            board = attach_ownership(build_decision_board(frame, config, decision), snapshot)
            board["data_mode"] = trust["data_mode"]
            board["model_version"] = trust["model_version"]
            board["projection_artifact_file_modified_at"] = trust[
                "projection_artifact_file_modified_at"
            ]
            board["missing_inputs"] = [
                list(trust["missing_inputs"]) for _ in range(len(board))
            ]
            return frame_records(board)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/leagues/{league_id}/players/{player_id}/intelligence")
    def player_intelligence(league_id: str, player_id: str) -> dict[str, object]:
        try:
            contract, _ = player_contract(league_id, player_id)
            return contract
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/leagues/{league_id}/players/{player_id}/shadow")
    def player_shadow(league_id: str, player_id: str) -> dict[str, object]:
        try:
            contract, config = player_contract(league_id, player_id)
            comparison = graph.player_comparison(
                player_id,
                production_week_projection=weekly_projection(contract),
            )
            scoring = graph_contract_status(config)
            comparison["scoring_contract"] = scoring
            comparison["decision_comparable"] = bool(
                comparison.get("comparable_horizon") and scoring.get("comparable")
            )
            return {
                "data_mode": "RESEARCH_SHADOW",
                "player_id": player_id,
                "graph_health": graph.health(),
                "comparison": comparison,
                "opportunity": graph.opportunity_audit(player_id),
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/leagues/{league_id}/players/{player_id}/scenario")
    def player_scenario(
        league_id: str,
        player_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        try:
            contract, config = player_contract(league_id, player_id)
            controls = ScenarioControls(
                role_multiplier=float(payload.get("role_multiplier", 1.0)),
                team_volume_multiplier=float(payload.get("team_volume_multiplier", 1.0)),
                availability_probability=(
                    float(payload["availability_probability"])
                    if payload.get("availability_probability") is not None
                    else None
                ),
            )
            raw = contract.get("raw_model_fields")
            raw_fields = raw if isinstance(raw, dict) else {}
            baseline_availability = raw_fields.get("availability_probability")
            try:
                baseline = float(baseline_availability)
            except (TypeError, ValueError):
                baseline = None
            result = graph.scenario_sensitivity(
                player_id,
                production_week_projection=weekly_projection(contract),
                baseline_availability=baseline,
                controls=controls,
            )
            result["scoring_contract"] = graph_contract_status(config)
            return result
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/portfolio/exposure")
    def portfolio_exposure() -> dict[str, object]:
        try:
            frame = projections() if projection_location.is_file() else None
            return build_portfolio_exposure([store, live_store], projections=frame)
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

    @app.get("/v1/model/shadow-evaluation")
    def model_shadow_evaluation() -> dict[str, object]:
        return shadow_evaluation_payload()

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
            "player_state_graph": {
                "health": graph.health(),
                "manifest": graph_manifest(),
                "shadow_evaluation": shadow_evaluation_payload(),
            },
            "diagnostics": diagnostics,
            "benchmark": summary.get("benchmark", []),
            "conformal": summary.get("conformal", []),
            "frozen_opportunity": summary.get("frozen_opportunity", []),
            "historical_sources": summary.get("historical_sources", []),
            "historical_source_coverage": summary.get("historical_source_coverage", []),
        }
