from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_RELEASE = "https://github.com/nflverse/nflverse-data/releases/download/injuries"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(season: int, output_dir: Path) -> dict[str, object]:
    name = f"injuries_{season}"
    url = f"{_RELEASE}/injuries_{season}.csv"
    path = output_dir / f"{name}.csv"
    if not path.is_file():
        temporary = path.with_suffix(path.suffix + ".partial")
        if temporary.exists():
            temporary.unlink()
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "nfl-player-state-engine/historical-injury-experiment"},
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
    return {
        "name": name,
        "url": url,
        "path": path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "status": "available",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Acquire only the nflverse historical injury files needed for the official-availability "
            "ablation and freeze their exact bytes in a checksum manifest."
        )
    )
    parser.add_argument("--seasons", nargs="+", type=int, default=[2021, 2022, 2023, 2024])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/historical_injury_archive"),
    )
    args = parser.parse_args()

    seasons = sorted(set(int(season) for season in args.seasons))
    if not seasons:
        raise ValueError("--seasons cannot be empty")
    if any(season > 2024 for season in seasons):
        raise ValueError("The certified nflverse historical injury archive ends with the 2024 season")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = [_download(season, args.output_dir) for season in seasons]
    frame = pd.DataFrame(records)
    frame.to_csv(args.output_dir / "SOURCE_MANIFEST.csv", index=False)
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "authority": "frozen_historical_injury_archive",
        "seasons": seasons,
        "files": records,
    }
    (args.output_dir / "SOURCE_MANIFEST.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
