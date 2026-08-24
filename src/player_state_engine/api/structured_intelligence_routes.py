from __future__ import annotations

import os
from pathlib import Path

from player_state_engine.intelligence.structured import ClaimDomain
from player_state_engine.product.structured_intelligence import StructuredIntelligenceArtifactStore

try:
    from fastapi import FastAPI, HTTPException, Query
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


def install_structured_intelligence_routes(
    app: FastAPI,
    *,
    artifact_root: str | Path | None = None,
    activation_registry_path: str | Path | None = None,
) -> None:
    """Expose timestamped intelligence evidence without any mutation or promotion path."""

    store = StructuredIntelligenceArtifactStore(
        artifact_root
        or os.getenv("PSE_STRUCTURED_INTELLIGENCE_ROOT", "artifacts/structured_intelligence"),
        activation_registry_path=(
            activation_registry_path
            or os.getenv(
                "PSE_INTELLIGENCE_ACTIVATION_REGISTRY",
                "config/intelligence_activation.json",
            )
        ),
    )

    @app.get("/v1/model/structured-intelligence")
    def structured_intelligence(
        as_of: str | None = Query(None),
        player_id: str | None = Query(None, min_length=1, max_length=128),
        domain: ClaimDomain | None = Query(None),
    ) -> dict[str, object]:
        try:
            return store.snapshot(
                as_of_utc=as_of,
                player_id=player_id,
                domain=domain,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/v1/model/structured-intelligence/health")
    def structured_intelligence_health() -> dict[str, object]:
        return store.health()

    @app.get("/v1/model/structured-intelligence/claims")
    def structured_intelligence_claims(
        as_of: str | None = Query(None),
        player_id: str | None = Query(None, min_length=1, max_length=128),
        domain: ClaimDomain | None = Query(None),
        limit: int = Query(200, ge=1, le=2000),
    ) -> dict[str, object]:
        try:
            return store.claims_snapshot(
                as_of_utc=as_of,
                player_id=player_id,
                domain=domain,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
