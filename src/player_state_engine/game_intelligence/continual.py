from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(slots=True)
class GameIntelligenceManifest:
    model_id: str
    created_at_utc: str
    feature_cutoff: str
    code_version: str
    data_hashes: dict[str, str]
    metrics: dict[str, float]
    promoted: bool
    promotion_reasons: list[str] = field(default_factory=list)
    evidence_tiers: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_game_intelligence_manifest(
    *,
    model_id: str,
    feature_cutoff: str,
    code_version: str,
    data_paths: dict[str, str | Path],
    metrics: dict[str, float],
    promoted: bool,
    promotion_reasons: list[str] | None = None,
    evidence_tiers: dict[str, str] | None = None,
    notes: list[str] | None = None,
) -> GameIntelligenceManifest:
    hashes = {name: sha256_file(path) for name, path in data_paths.items() if Path(path).exists()}
    return GameIntelligenceManifest(
        model_id=model_id,
        created_at_utc=datetime.now(UTC).isoformat(),
        feature_cutoff=feature_cutoff,
        code_version=code_version,
        data_hashes=hashes,
        metrics={key: float(value) for key, value in metrics.items()},
        promoted=bool(promoted),
        promotion_reasons=list(promotion_reasons or []),
        evidence_tiers=dict(evidence_tiers or {}),
        notes=list(notes or []),
    )


def append_game_intelligence_registry(
    path: str | Path,
    manifest: GameIntelligenceManifest,
) -> Path:
    registry_path = Path(path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    if registry_path.exists():
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Game intelligence registry must contain a JSON list")
    else:
        payload = []
    payload.append(manifest.to_dict())
    registry_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return registry_path
