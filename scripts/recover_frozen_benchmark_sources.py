from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matches(path: Path, record: dict[str, object]) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == int(record["bytes"])
        and _sha256(path) == str(record["sha256"]).lower()
    )


def _records(manifest_path: Path) -> dict[str, dict[str, object]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, list):
        raise ValueError("Frozen benchmark manifest must contain a source list")
    return {
        str(record["name"]): record
        for record in sources
        if isinstance(record, dict) and record.get("name")
    }


def _copy_cached_player_sources(
    records: dict[str, dict[str, object]], cache_root: Path, output_dir: Path
) -> list[dict[str, object]]:
    recovered: list[dict[str, object]] = []
    for name, record in sorted(records.items()):
        if not name.startswith("player_stats_"):
            continue
        source = cache_root / Path(str(record["url"])).name
        destination = output_dir / source.name
        if not _matches(source, record):
            recovered.append(
                {
                    "name": name,
                    "source": source.as_posix(),
                    "status": "cache_missing_or_hash_mismatch",
                }
            )
            continue
        shutil.copyfile(source, destination)
        recovered.append(
            {
                "name": name,
                "source": source.as_posix(),
                "destination": destination.as_posix(),
                "sha256": _sha256(destination),
                "bytes": destination.stat().st_size,
                "status": "recovered_from_actions_cache",
            }
        )
    return recovered


def _recover_schedule(
    record: dict[str, object], output_dir: Path, commits: list[str]
) -> dict[str, object]:
    destination = output_dir / Path(str(record["url"])).name
    if _matches(destination, record):
        return {
            "name": "schedules",
            "destination": destination.as_posix(),
            "status": "already_exact",
            "sha256": _sha256(destination),
            "bytes": destination.stat().st_size,
        }

    attempts: list[dict[str, object]] = []
    for commit in commits:
        url = f"https://raw.githubusercontent.com/nflverse/nfldata/{commit}/data/games.csv"
        temporary = destination.with_suffix(f".{commit[:8]}.partial")
        if temporary.exists():
            temporary.unlink()
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "nfl-player-state-engine/frozen-schedule-recovery"},
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as target:
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
            attempt = {
                "commit": commit,
                "url": url,
                "bytes": temporary.stat().st_size,
                "sha256": _sha256(temporary),
            }
            attempts.append(attempt)
            if _matches(temporary, record):
                temporary.replace(destination)
                return {
                    "name": "schedules",
                    "destination": destination.as_posix(),
                    "status": "recovered_from_nfldata_git_history",
                    "commit": commit,
                    "sha256": _sha256(destination),
                    "bytes": destination.stat().st_size,
                    "attempts": attempts,
                }
        finally:
            if temporary.exists():
                temporary.unlink()

    raise ValueError(
        "No supplied nfldata commit reproduced the frozen schedule bytes. Attempts: "
        + json.dumps(attempts, sort_keys=True)
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Recover content-addressed benchmark inputs from the preserved July Actions cache and "
            "the nfldata Git history. Every recovered file must match the original frozen manifest."
        )
    )
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=Path("artifacts/reports/benchmark_real/DATA_MANIFEST.json"),
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path("data/raw/nflverse"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/frozen_benchmark_sources"),
    )
    parser.add_argument(
        "--schedule-commits",
        nargs="+",
        default=[
            "8f78101ffd9fe844a8b9a178245a6f0ddd870013",
            "208ae776ce8bc7a4196366cf74d36eef1d66c3af",
            "2a04d95393c1ce65c348f42c9acb316b043f707e",
            "0886d1fcfde27b7068bc655e3e46698ed97ea6b3",
        ],
    )
    args = parser.parse_args()

    records = _records(args.benchmark_manifest)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    recovered = _copy_cached_player_sources(records, args.cache_root, args.output_dir)
    schedule = _recover_schedule(records["schedules"], args.output_dir, args.schedule_commits)
    payload = {
        "schema_version": 1,
        "authority": "content_addressed_recovery",
        "benchmark_manifest": args.benchmark_manifest.as_posix(),
        "cache_root": args.cache_root.as_posix(),
        "player_sources": recovered,
        "schedule": schedule,
    }
    output = args.output_dir / "RECOVERY_MANIFEST.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
