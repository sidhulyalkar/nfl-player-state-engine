from __future__ import annotations

import json
import os
from pathlib import Path

import joblib

from player_state_engine.data.io import read_table
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.schema import MatchupSpec, SimulationConfig
from player_state_engine.game_intelligence.simulator import simulate_matchup
from player_state_engine.game_intelligence.sources import game_evidence_catalog
from player_state_engine.product.provenance import frame_records

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


class GameSimulationRequest(BaseModel):
    season: int
    week: int = Field(ge=1, le=22)
    home_team: str
    away_team: str
    game_id: str | None = None
    home_spread: float = 0.0
    game_total: float = 44.0
    simulations: int = Field(default=250, ge=25, le=5000)
    scoring: str = "ppr"
    seed: int = 42


def _latest_artifact_dir(root: Path) -> Path | None:
    direct = root / "game_models.joblib"
    if direct.exists():
        return root
    candidates = sorted(
        (path for path in root.glob("**/game_models.joblib") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0].parent if candidates else None


def _read_registry(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def install_game_intelligence_routes(
    app: FastAPI,
    *,
    artifact_root: str | Path | None = None,
    registry_path: str | Path | None = None,
) -> None:
    root = Path(
        artifact_root
        or os.getenv("PSE_GAME_INTELLIGENCE_ROOT", "artifacts/game_intelligence/weekly")
    )
    registry = Path(
        registry_path
        or os.getenv(
            "PSE_GAME_INTELLIGENCE_REGISTRY",
            "artifacts/models/game_intelligence/registry.json",
        )
    )

    @app.get("/v1/research/game-intelligence/sources")
    def game_intelligence_sources() -> dict[str, object]:
        return {
            "sources": game_evidence_catalog(),
            "retrospective_sources_allowed_in_live_prediction": False,
            "production_projection_changed": False,
        }

    @app.get("/v1/research/game-intelligence/status")
    def game_intelligence_status() -> dict[str, object]:
        entries = _read_registry(registry)
        latest = entries[-1] if entries else None
        artifact_dir = _latest_artifact_dir(root) if root.exists() else None
        return {
            "model_family": "game_intelligence_v010_research",
            "latest_registry_entry": latest,
            "registry_entries": len(entries),
            "artifact_available": artifact_dir is not None,
            "artifact_dir": str(artifact_dir) if artifact_dir is not None else None,
            "production_projection_changed": False,
            "automatic_promotion": False,
        }

    @app.post("/v1/research/game-intelligence/simulate")
    def simulate_game(request: GameSimulationRequest) -> dict[str, object]:
        artifact_dir = _latest_artifact_dir(root) if root.exists() else None
        if artifact_dir is None:
            raise HTTPException(
                status_code=503,
                detail=f"No game-intelligence research artifact available under {root}",
            )
        model_path = artifact_dir / "game_models.joblib"
        tendency_path = artifact_dir / "team_tendencies.parquet"
        usage_path = artifact_dir / "player_usage_next_week.parquet"
        if not usage_path.exists():
            usage_path = artifact_dir / "player_usage.parquet"
        if not tendency_path.exists() or not usage_path.exists():
            raise HTTPException(
                status_code=503,
                detail="Game-intelligence artifact is missing tendencies or usage state.",
            )
        payload = joblib.load(model_path)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=503, detail="Invalid game model artifact.")
        play_call_model = payload.get("play_call_model")
        outcome_model = payload.get("outcome_model")
        if outcome_model is None:
            raise HTTPException(status_code=503, detail="Outcome model missing from artifact.")
        matchup = MatchupSpec(
            season=request.season,
            week=request.week,
            home_team=request.home_team,
            away_team=request.away_team,
            game_id=request.game_id,
            home_spread=request.home_spread,
            game_total=request.game_total,
        )
        result = simulate_matchup(
            matchup,
            tendencies=read_table(tendency_path),
            usage=read_table(usage_path),
            outcome_model=outcome_model,
            play_call_model=play_call_model,
            league_config=LeagueConfig(scoring=request.scoring),
            config=SimulationConfig(simulations=request.simulations, seed=request.seed),
        )
        return {
            "game": frame_records(result.game_summary),
            "teams": frame_records(result.team_summary),
            "players": frame_records(result.player_summary),
            "diagnostics": result.diagnostics,
            "research_only": True,
            "promoted": False,
            "production_projection_changed": False,
        }
