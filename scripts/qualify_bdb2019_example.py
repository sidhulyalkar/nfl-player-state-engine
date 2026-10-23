#!/usr/bin/env python3
"""Qualify a locally authorized copy of the official 2019 NFL Big Data Bowl sample.

Run python scripts/qualify_bdb2019_example.py --help for usage.
Source files and recorded coordinates are never added to this repository.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from player_state_engine.product.bdb2019_source_qualification import (
    SOURCE_COMMIT,
    SOURCE_FILES,
    SOURCE_GAME_ID,
    file_identifiers,
    qualify_bdb2019_play,
    write_qualification_report,
)
from player_state_engine.product.gameday_tracking import write_replay_json

SOURCE_HOST = "raw.githubusercontent.com"
SOURCE_PATH = "nfl-football-ops/Big-Data-Bowl"
MAX_DOWNLOAD_BYTES = {
    "tracking": 40_000_000,
    "plays": 5_000_000,
    "games": 50_000,
}


def download_pinned_sources(source_dir: Path) -> None:
    """Fetch only three pinned files from the immutable official source revision.

    Requires rights acknowledgment in the CLI before this function is invoked.
    Rejects changed files, oversized responses and any download that does not
    match the exact Git blob identity from the reviewed source revision.
    """
    source_dir.mkdir(parents=True, exist_ok=True)
    for kind, (filename, expected_sha1, expected_bytes) in SOURCE_FILES.items():
        destination = source_dir / filename
        if destination.exists():
            identity = file_identifiers(destination)
            if identity["git_blob_sha1"] != expected_sha1 or identity["bytes"] != expected_bytes:
                raise ValueError(
                    f"Existing {kind} file does not match pinned NFL source; refusing to overwrite: "
                    f"{destination}"
                )
            print(f"Verified existing {kind} source file.")
            continue

        url = f"https://{SOURCE_HOST}/{SOURCE_PATH}/{SOURCE_COMMIT}/Data/{filename}"
        temp = destination.with_name(destination.name + ".pse-download-partial")
        if temp.exists():
            raise ValueError(f"Refusing to overwrite an existing partial download: {temp}")
        req = Request(url, headers={"User-Agent": "NFL-Player-State-Engine-Research-Qualifier/1.0"})
        try:
            with urlopen(req, timeout=45) as response, temp.open("xb") as stream:
                resolved = urlparse(response.geturl())
                if resolved.scheme != "https" or resolved.hostname != SOURCE_HOST:
                    raise ValueError("Unexpected NFL source download redirect.")
                total = 0
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES[kind]:
                        raise ValueError(f"{kind} source exceeded safety size limit.")
                    stream.write(chunk)
            actual = file_identifiers(temp)
            if actual["git_blob_sha1"] != expected_sha1 or actual["bytes"] != expected_bytes:
                raise ValueError(f"{kind} download failed pinned official Git object verification.")
            os.replace(temp, destination)
            print(f"Verified official {kind} file: {actual['sha256'][:16]}... SHA-256.")
        finally:
            temp.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True, help="Private directory with the three official Data/*.csv files")
    parser.add_argument("--output-dir", type=Path, required=True, help="Local private directory for research-only replay and qualification report")
    parser.add_argument("--download", action="store_true", help="Fetch exact pinned official CSV bytes to source-dir, if absent")
    parser.add_argument("--game-id", default=SOURCE_GAME_ID, help="Official pinned tracking game (default 2017090700)")
    parser.add_argument("--play-id", default="938", help="Exact play identifier (default NFL's published tutorial play 938)")
    parser.add_argument("--license-id", required=True, help="Identifier of the actual source terms you reviewed; not a grant of license")
    parser.add_argument(
        "--acknowledge-source-terms",
        action="store_true",
        help="Explicitly attest authorized research access and review applicable NFL source terms",
    )
    parser.add_argument("--report-only", action="store_true", help="Do not write the replay positions JSON")
    args = parser.parse_args()
    if not args.acknowledge_source_terms or not args.license_id.strip():
        parser.error("Review and explicitly acknowledge applicable NFL source terms and supply --license-id.")
    if args.source_dir.resolve() == args.output_dir.resolve():
        parser.error("Keep source CSV files separate from normalized replay outputs.")
    if args.download:
        download_pinned_sources(args.source_dir)
    report, replay = qualify_bdb2019_play(
        args.source_dir,
        game_id=args.game_id,
        play_id=args.play_id,
        license_acknowledged=args.acknowledge_source_terms,
        license_identifier=args.license_id,
    )
    report_path = write_qualification_report(
        report, args.output_dir / f"{args.game_id}-{args.play_id}-qualification.json"
    )
    if not args.report_only:
        replay_path = write_replay_json(
            replay, args.output_dir / f"{args.game_id}-{args.play_id}-research-replay.json"
        )
        print(f"Research-only replay JSON: {replay_path}")
    print(f"Qualification summary: {report_path}")
    print(f"Status: {report['qualification_status']}; recorded frame count: {replay['frame_count']}")
    print("NOT VIDEO-ALIGNED. NOT LIVE. NO COMMERCIAL/TRAINING RIGHTS GRANTED.")


if __name__ == "__main__":
    main()
