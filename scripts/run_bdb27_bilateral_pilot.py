"""Offline, no-download pilot for canonical trajectory CSVs, never production features."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from player_state_engine.research.bilateral import asymmetry_profiles, extract_turn_events


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(input_csv: Path, output_dir: Path, *, synthetic: bool = False) -> dict:
    if not input_csv.is_file():
        raise ValueError("canonical input CSV does not exist")
    if input_csv.resolve() == output_dir.resolve():
        raise ValueError("output must not overwrite input")
    raw_hash = digest(input_csv)
    raw = pd.read_csv(input_csv)
    events = extract_turn_events(raw)
    profiles = asymmetry_profiles(events)
    output_dir.mkdir(parents=True, exist_ok=True)
    events.to_csv(output_dir / "events.csv", index=False)
    profiles.to_csv(output_dir / "asymmetry_profiles.csv", index=False)
    manifest = {
        "schema_version": 1,
        "authority": "RESEARCH_ONLY_NO_PROMOTION",
        "input_sha256": raw_hash,
        "source": "synthetic_fixture" if synthetic else "user_supplied_canonical_tracking",
        "frames": int(len(raw)),
        "events": int(len(events)),
        "profiles": int(len(profiles)),
        "estimated_profiles": int(profiles.status.eq("estimated").sum()) if len(profiles) else 0,
        "limitations": [
            "path-left and path-right are not anatomical plant-leg identities",
            "no gaze, cognition, joint loading, or injury risk are inferred",
            "no official dataset provenance or rights are authenticated",
            "held-out NFL outcome validation not performed",
        ],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--synthetic-fixture", action="store_true", help="explicitly mark generated test data")
    args = parser.parse_args()
    print(json.dumps(run(args.input_csv, args.output_dir, synthetic=args.synthetic_fixture), indent=2))


if __name__ == "__main__":
    main()
