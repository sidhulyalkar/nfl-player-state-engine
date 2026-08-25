from __future__ import annotations

import os
from pathlib import Path

from player_state_engine.product.evidence_artifacts import EvidenceArtifactStore

try:
    from fastapi import FastAPI, Query
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


def install_evidence_routes(
    app: FastAPI,
    *,
    evidence_factory_root: str | Path | None = None,
) -> None:
    """Expose frozen Evidence Factory artifacts without changing model authority."""

    store = EvidenceArtifactStore(
        evidence_factory_root
        or os.getenv("PSE_EVIDENCE_FACTORY_ROOT", "artifacts/evidence_factory")
    )

    @app.get("/v1/model/evidence-factory")
    def evidence_factory(
        target: str | None = Query(None, pattern="^[a-z0-9_]+$"),
    ) -> dict[str, object]:
        return store.snapshot(target=target)
