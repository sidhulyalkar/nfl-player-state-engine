from __future__ import annotations

import argparse
import csv
import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

_DEFAULT_REGISTRY = Path("experiments/historical_official_availability_v2/registered_inputs.json")
_DEFAULT_NUMERICAL_ROOT = Path("data/raw/historical_numerical_baseline_v2")
_DEFAULT_INJURY_ROOT = Path("data/raw/historical_injury_archive_v2")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_name(record: dict[str, object]) -> str:
    source_url = str(record.get("source_url") or "")
    name = Path(urlparse(source_url).path).name
    if not name:
        raise ValueError(f"Registered source has no downloadable file name: {record}")
    return name


def _matches(path: Path, record: dict[str, object]) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == int(record["bytes"])
        and _sha256(path) == str(record["sha256"])
    )


def _download_verified(record: dict[str, object], path: Path) -> str:
    if _matches(path, record):
        return "reused_exact"

    url = str(record.get("source_url") or "")
    if not url:
        raise ValueError(f"Registered source has no source_url: {record}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "nfl-player-state-engine/registered-historical-v2"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as target:
            while chunk := response.read(1024 * 1024):
                target.write(chunk)
        if temporary.stat().st_size != int(record["bytes"]):
            raise ValueError(
                f"Registered source byte mismatch after download for {path.name}: "
                f"expected {record['bytes']}, found {temporary.stat().st_size}"
            )
        actual_sha = _sha256(temporary)
        if actual_sha != str(record["sha256"]):
            raise ValueError(
                f"Registered source SHA-256 mismatch after download for {path.name}: "
                f"expected {record['sha256']}, found {actual_sha}"
            )
        temporary.replace(path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return "downloaded_exact"


def _rehydrate_numerical(
    registry: dict[str, object], root: Path
) -> tuple[list[dict[str, object]], dict[str, str]]:
    baseline = registry.get("numerical_baseline")
    if not isinstance(baseline, dict):
        raise ValueError("Registry is missing numerical_baseline")
    files = baseline.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Registered numerical source list is empty")

    records: list[dict[str, object]] = []
    recovery: dict[str, str] = {}
    for raw in files:
        if not isinstance(raw, dict):
            raise ValueError("Registered numerical source record is not an object")
        path = root / _file_name(raw)
        recovery[str(raw["name"])] = _download_verified(raw, path)
        record = {
            "name": str(raw["name"]),
            "path": path.as_posix(),
            "source_url": str(raw["source_url"]),
            "source_commit": raw.get("source_commit"),
            "bytes": int(raw["bytes"]),
            "sha256": str(raw["sha256"]),
        }
        records.append(record)

    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "authority": "registered_historical_numerical_baseline_v2_rehydration",
        "baseline_id": str(baseline["baseline_id"]),
        "identity_sha256": str(baseline["identity_sha256"]),
        "seasons": [int(season) for season in registry["evaluation_contract"]["seasons"]],
        "schedule_commit": str(baseline["schedule_commit"]),
        "files": records,
        "historical_production_parity_verified": False,
        "interpretation": (
            "Rehydrated only after every downloaded file matched the registered byte count and "
            "SHA-256. This reproduces the v2 research source identity, not July production parity."
        ),
    }
    (root / "NUMERICAL_BASELINE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return records, recovery


def _rehydrate_injuries(
    registry: dict[str, object], root: Path
) -> tuple[list[dict[str, object]], dict[str, str]]:
    archive = registry.get("injury_archive")
    if not isinstance(archive, dict):
        raise ValueError("Registry is missing injury_archive")
    files = archive.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Registered injury source list is empty")

    records: list[dict[str, object]] = []
    recovery: dict[str, str] = {}
    for raw in files:
        if not isinstance(raw, dict):
            raise ValueError("Registered injury source record is not an object")
        path = root / _file_name(raw)
        recovery[str(raw["name"])] = _download_verified(raw, path)
        records.append(
            {
                "name": str(raw["name"]),
                "url": str(raw["source_url"]),
                "path": path.as_posix(),
                "bytes": int(raw["bytes"]),
                "sha256": str(raw["sha256"]),
                "status": "available_registered_exact",
            }
        )

    root.mkdir(parents=True, exist_ok=True)
    with (root / "SOURCE_MANIFEST.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["name", "url", "path", "bytes", "sha256", "status"],
        )
        writer.writeheader()
        writer.writerows(records)
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "authority": "registered_historical_injury_archive_v2_rehydration",
        "identity_sha256": str(archive["identity_sha256"]),
        "seasons": [int(season) for season in registry["evaluation_contract"]["seasons"]],
        "files": records,
        "interpretation": (
            "Rehydrated only after every injury file matched the registered byte count and SHA-256."
        ),
    }
    (root / "SOURCE_MANIFEST.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return records, recovery


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Rehydrate the exact registered historical official-availability v2 source bytes. "
            "Mutable upstream URLs are acquisition locations only: any byte or SHA drift aborts "
            "the operation before a manifest is accepted."
        )
    )
    parser.add_argument("--registry", type=Path, default=_DEFAULT_REGISTRY)
    parser.add_argument("--numerical-root", type=Path, default=_DEFAULT_NUMERICAL_ROOT)
    parser.add_argument("--injury-root", type=Path, default=_DEFAULT_INJURY_ROOT)
    args = parser.parse_args()

    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    if registry.get("authority") != "research_evidence_only":
        raise ValueError("Registered source rehydration requires research_evidence_only authority")
    numerical, numerical_recovery = _rehydrate_numerical(registry, args.numerical_root)
    injuries, injury_recovery = _rehydrate_injuries(registry, args.injury_root)
    summary = {
        "registry": args.registry.as_posix(),
        "registry_sha256": _sha256(args.registry),
        "numerical_baseline_identity_sha256": registry["numerical_baseline"]["identity_sha256"],
        "injury_archive_identity_sha256": registry["injury_archive"]["identity_sha256"],
        "numerical_files": len(numerical),
        "injury_files": len(injuries),
        "numerical_recovery": numerical_recovery,
        "injury_recovery": injury_recovery,
        "authority": "research_evidence_only",
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
