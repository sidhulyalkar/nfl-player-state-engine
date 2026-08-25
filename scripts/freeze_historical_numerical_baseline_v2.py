from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

_RELEASE = "https://github.com/nflverse/nflverse-data/releases/download/stats_player"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "nfl-player-state-engine/historical-baseline-v2"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as target:
            while chunk := response.read(1024 * 1024):
                target.write(chunk)
        temporary.replace(path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _github_json(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "nfl-player-state-engine/historical-baseline-v2",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _latest_schedule_commit() -> str:
    query = urllib.parse.urlencode({"path": "data/games.csv", "per_page": 1})
    payload = _github_json(f"https://api.github.com/repos/nflverse/nfldata/commits?{query}")
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ValueError("Unable to resolve the current nfldata games.csv commit")
    commit = str(payload[0].get("sha") or "").strip()
    if not commit:
        raise ValueError("nfldata games.csv commit response did not contain a SHA")
    return commit


def _record(name: str, path: Path, source_url: str, *, source_commit: str | None = None) -> dict[str, object]:
    return {
        "name": name,
        "path": path.as_posix(),
        "source_url": source_url,
        "source_commit": source_commit,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _identity(records: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for row in sorted(records, key=lambda item: str(item["name"])):
        digest.update(str(row["name"]).encode("utf-8"))
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(str(row["bytes"]).encode("ascii"))
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze a new content-addressed historical numerical baseline for the official-"
            "availability v2 experiment. Mutable release URLs are accepted only as acquisition "
            "locations; the resulting artifact identity is the SHA-256 manifest, and schedules "
            "are pinned to an exact nfldata Git commit."
        )
    )
    parser.add_argument("--seasons", nargs="+", type=int, default=[2020, 2021, 2022, 2023, 2024])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/historical_numerical_baseline_v2"),
    )
    args = parser.parse_args()

    seasons = sorted(set(int(season) for season in args.seasons))
    if not seasons:
        raise ValueError("--seasons cannot be empty")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, object]] = []
    for season in seasons:
        url = f"{_RELEASE}/stats_player_week_{season}.csv"
        path = args.output_dir / f"stats_player_week_{season}.csv"
        _download(url, path)
        records.append(_record(f"player_stats_{season}", path, url))

    schedule_commit = _latest_schedule_commit()
    schedule_url = (
        f"https://raw.githubusercontent.com/nflverse/nfldata/{schedule_commit}/data/games.csv"
    )
    schedule_path = args.output_dir / "games.csv"
    _download(schedule_url, schedule_path)
    records.append(
        _record(
            "schedules",
            schedule_path,
            schedule_url,
            source_commit=schedule_commit,
        )
    )

    identity = _identity(records)
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "authority": "frozen_historical_numerical_baseline_v2",
        "baseline_id": f"historical-numerical-v2-{identity[:20]}",
        "identity_sha256": identity,
        "seasons": seasons,
        "schedule_commit": schedule_commit,
        "files": records,
        "historical_production_parity_verified": False,
        "interpretation": (
            "This is a newly frozen historical numerical baseline acquired for a fresh research "
            "experiment. It is not the July benchmark source identity and does not claim historical "
            "production parity. Exact file hashes and the pinned schedule commit define this run."
        ),
    }
    (args.output_dir / "NUMERICAL_BASELINE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
