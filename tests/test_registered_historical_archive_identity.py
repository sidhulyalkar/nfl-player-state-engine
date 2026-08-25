from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))
from verify_registered_historical_archive_v2 import (  # noqa: E402
    verify_registered_injury_archive,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_identity(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.name.encode("utf-8"))
    digest.update(_sha(path).encode("ascii"))
    return digest.hexdigest()


def _write_fixture(tmp_path: Path, *, registered_identity: str | None = None) -> tuple[Path, Path]:
    injury = tmp_path / "injuries_2020.csv"
    injury.write_text("season,week\n2020,1\n", encoding="utf-8")
    manifest = pd.DataFrame(
        [
            {
                "name": "injuries_2020",
                "url": "https://example.test/injuries_2020.csv",
                "path": injury.as_posix(),
                "bytes": injury.stat().st_size,
                "sha256": _sha(injury),
                "status": "available",
            }
        ]
    )
    manifest.to_csv(tmp_path / "SOURCE_MANIFEST.csv", index=False)
    registry = {
        "injury_archive": {
            "identity_sha256": registered_identity or _canonical_identity(injury),
            "files": [
                {
                    "name": "injuries_2020",
                    "bytes": injury.stat().st_size,
                    "sha256": _sha(injury),
                    "source_url": "https://example.test/injuries_2020.csv",
                }
            ],
        }
    }
    registry_path = tmp_path / "registered_inputs.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    return registry_path, injury


def test_canonical_registered_injury_identity_matches_source_verifier(tmp_path: Path) -> None:
    registry_path, injury = _write_fixture(tmp_path)
    assert verify_registered_injury_archive(registry_path, tmp_path) == _canonical_identity(injury)


def test_canonical_registered_injury_identity_rejects_aggregate_drift(tmp_path: Path) -> None:
    registry_path, _ = _write_fixture(tmp_path, registered_identity="0" * 64)
    with pytest.raises(ValueError, match="aggregate identity mismatch"):
        verify_registered_injury_archive(registry_path, tmp_path)
