from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from player_state_engine.evaluation.historical_intelligence_corpus import (
    verify_source_archive_manifest,
)

_DEFAULT_REGISTRY = Path("experiments/historical_official_availability_v2/registered_inputs.json")
_DEFAULT_INJURY_ROOT = Path("data/raw/historical_injury_archive_v2")


def _registered_injury_paths(registry: dict[str, object], root: Path) -> list[Path]:
    archive = registry.get("injury_archive")
    if not isinstance(archive, dict):
        raise ValueError("Registry is missing injury_archive")
    files = archive.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Registry contains no injury source files")

    paths: list[Path] = []
    for raw in files:
        if not isinstance(raw, dict):
            raise ValueError("Registered injury source record is not an object")
        source_url = str(raw.get("source_url") or "")
        filename = Path(urlparse(source_url).path).name
        if not filename:
            raise ValueError(f"Registered injury source has no filename: {raw}")
        paths.append(root / filename)
    return paths


def verify_registered_injury_archive(
    registry_path: Path,
    injury_root: Path,
) -> str:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict):
        raise ValueError("Registered experiment contract is not a JSON object")
    archive = registry.get("injury_archive")
    if not isinstance(archive, dict):
        raise ValueError("Registry is missing injury_archive")
    expected_identity = str(archive.get("identity_sha256") or "")
    if not expected_identity:
        raise ValueError("Registry is missing injury_archive.identity_sha256")

    manifest_path = injury_root / "SOURCE_MANIFEST.csv"
    manifest = pd.read_csv(manifest_path)
    verification = verify_source_archive_manifest(
        _registered_injury_paths(registry, injury_root),
        manifest,
    )
    if not verification.verified or not verification.archive_identity_sha256:
        raise ValueError(
            "Registered injury archive source verification failed: "
            + "; ".join(verification.failures)
        )
    actual_identity = verification.archive_identity_sha256
    if actual_identity != expected_identity:
        raise ValueError(
            "Registered injury archive aggregate identity mismatch: "
            f"expected {expected_identity}, found {actual_identity}"
        )
    return actual_identity


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the exact registered historical injury source bytes and recompute the canonical "
            "archive identity using the same algorithm as the historical intelligence corpus."
        )
    )
    parser.add_argument("--registry", type=Path, default=_DEFAULT_REGISTRY)
    parser.add_argument("--injury-root", type=Path, default=_DEFAULT_INJURY_ROOT)
    args = parser.parse_args()

    identity = verify_registered_injury_archive(args.registry, args.injury_root)
    print(f"REGISTERED_INJURY_ARCHIVE_IDENTITY_VERIFIED={identity}")


if __name__ == "__main__":
    main()
