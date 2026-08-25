from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from player_state_engine.evaluation.historical_intelligence_experiment import (
    verify_frozen_benchmark_sources,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_records(
    manifest: dict[str, object], seasons: tuple[int, ...]
) -> list[dict[str, object]]:
    records = {
        str(record.get("name")): record
        for record in manifest.get("sources", [])
        if isinstance(record, dict) and record.get("name")
    }
    evaluation = sorted(set(int(season) for season in seasons))
    if not evaluation:
        raise ValueError("--seasons cannot be empty")
    years = list(evaluation)
    prior = evaluation[0] - 1
    if f"player_stats_{prior}" in records:
        years.insert(0, prior)
    names = [*(f"player_stats_{season}" for season in years), "schedules"]
    missing = [name for name in names if name not in records]
    if missing:
        raise ValueError(f"Frozen benchmark manifest is missing sources: {missing}")
    return [records[name] for name in names]


def _download_verified(record: dict[str, object], output_dir: Path) -> Path:
    name = str(record["name"])
    url = str(record.get("url", "")).strip()
    expected_sha = str(record.get("sha256", "")).strip().lower()
    expected_bytes = int(record["bytes"])
    if not url or not expected_sha:
        raise ValueError(f"Frozen benchmark source {name!r} lacks URL or SHA-256")
    basename = Path(urlparse(url).path).name
    if not basename:
        raise ValueError(f"Frozen benchmark source {name!r} has no URL basename")
    destination = output_dir / basename

    if destination.is_file():
        actual_sha = _sha256(destination)
        actual_bytes = destination.stat().st_size
        if actual_sha != expected_sha or actual_bytes != expected_bytes:
            raise ValueError(
                f"Existing source {destination} does not match the frozen manifest; refusing to "
                "overwrite potentially useful evidence"
            )
        return destination

    temporary = destination.with_suffix(destination.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "nfl-player-state-engine/frozen-replay"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as target:
            while chunk := response.read(1024 * 1024):
                target.write(chunk)
        actual_sha = _sha256(temporary)
        actual_bytes = temporary.stat().st_size
        if actual_sha != expected_sha or actual_bytes != expected_bytes:
            raise ValueError(
                f"Upstream bytes for {name!r} no longer match the frozen benchmark manifest "
                f"(expected sha256={expected_sha}, bytes={expected_bytes}; "
                f"received sha256={actual_sha}, bytes={actual_bytes}). The URL may be mutable; "
                "do not silently treat the new file as frozen evidence."
            )
        temporary.replace(destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Rehydrate the raw numerical benchmark inputs and accept each download only when its "
            "SHA-256 and byte count exactly match DATA_MANIFEST.json. Mutable upstream drift fails "
            "closed instead of rewriting the historical replay sample."
        )
    )
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=Path("artifacts/reports/benchmark_real/DATA_MANIFEST.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/frozen_benchmark_sources"),
    )
    parser.add_argument("--seasons", nargs="+", type=int, default=[2021, 2022, 2023, 2024])
    args = parser.parse_args()

    try:
        manifest = json.loads(args.benchmark_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Frozen benchmark manifest is unreadable: {args.benchmark_manifest}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), list):
        raise ValueError("Frozen benchmark manifest must contain a source list")

    seasons = tuple(sorted(set(int(season) for season in args.seasons)))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = [
        _download_verified(record, args.output_dir).as_posix()
        for record in _required_records(manifest, seasons)
    ]
    verification = verify_frozen_benchmark_sources(
        args.benchmark_manifest,
        args.output_dir,
        seasons=seasons,
    )
    if not verification.verified:
        raise ValueError(
            "Frozen benchmark source verification failed after acquisition: "
            + "; ".join(verification.failures)
        )

    payload = {
        "schema_version": 1,
        "authority": "frozen_source_archive",
        "benchmark_manifest": args.benchmark_manifest.as_posix(),
        "seasons": list(seasons),
        "source_identity_sha256": verification.source_identity_sha256,
        "downloaded_or_reused": downloaded,
        "files": list(verification.files),
    }
    output = args.output_dir / "SOURCE_MANIFEST.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
