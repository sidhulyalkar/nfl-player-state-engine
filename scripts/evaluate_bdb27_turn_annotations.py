"""Compare research turn detections to independent complete-trial human reviews."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from player_state_engine.research.bdb27_event_validation import evaluate_reviewed_events
from player_state_engine.research.bdb27_qualification import source_digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detections", required=True, type=Path)
    parser.add_argument("--reviewed-trials", required=True, type=Path)
    parser.add_argument("--human-labels", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--tolerance-s", type=float, default=0.2)
    args = parser.parse_args()
    paths = (args.detections, args.reviewed_trials, args.human_labels)
    if any(not p.is_file() or p.is_symlink() for p in paths):
        raise ValueError("input annotations must be real local CSV files")
    if any(args.output_dir.resolve() == p.resolve().parent for p in paths):
        raise ValueError("review outputs must not overwrite an input directory")
    score = evaluate_reviewed_events(pd.read_csv(args.detections),
                                     pd.read_csv(args.reviewed_trials),
                                     pd.read_csv(args.human_labels),
                                     tolerance_s=args.tolerance_s)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    score.to_csv(args.output_dir / "blind_event_validation_RESEARCH_ONLY.csv", index=False)
    manifest = {
        "schema_version": 1, "authority": "RESEARCH_ONLY_NO_PROMOTION",
        "tolerance_s": args.tolerance_s,
        "input_sha256": {p.name: source_digest(p) for p in paths},
        "raters": len(score),
        "limits": ["manual review validity depends on independent human labels",
                   "event-level matching is not cognitive reaction or awareness measurement",
                   "no actual NFL or Combine event-review data qualified by this CLI"],
    }
    (args.output_dir / "event_review_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
