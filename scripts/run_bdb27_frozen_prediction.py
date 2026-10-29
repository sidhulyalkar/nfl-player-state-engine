"""Run a private, prespecified 2027 rookie outcome experiment (research only).

Requires licensed source CSVs supplied locally and an independently prepared,
role-specific rookie outcome table with explicit numerator/denominator semantics.
No collection, model promotion, or upload of player-level NFL artifacts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from player_state_engine.research.bdb27_prediction import (
    build_panel,
    design_from_file,
    evaluate_panel,
    write_private_report,
)
from player_state_engine.research.bdb27_qualification import _header, _local_file, source_digest


def run(source_dir: Path, combine_dir: Path, outcomes_path: Path, design_path: Path,
        output_dir: Path, *, acknowledge_terms: bool = False,
        confirm_outcome_provenance: bool = False) -> dict:
    if not acknowledge_terms or not confirm_outcome_provenance:
        raise ValueError("explicit licensed-data and curated-outcome review acknowledgments required")
    source_dir = source_dir.resolve()
    combine_dir = combine_dir.resolve()
    output_dir = output_dir.resolve()
    for restricted in (source_dir, combine_dir):
        if output_dir == restricted or output_dir.is_relative_to(restricted):
            raise ValueError("output must not overwrite qualified sources")
    repository_root = Path(__file__).resolve().parents[1]
    if output_dir == repository_root or output_dir.is_relative_to(repository_root):
        raise ValueError("output must remain in a separately controlled private research directory")
    design = design_from_file(design_path)
    mpath = _local_file(combine_dir / "qualification_manifest.json")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    if manifest.get("authority") != "RESEARCH_ONLY_NO_PROMOTION":
        raise ValueError("Combine qualification authority mismatch")
    if manifest.get("coordinate_handedness") != "USER_DECLARED_NOT_VERIFIED":
        raise ValueError("unexpected Combine geometry authority")
    sources = manifest.get("sources", {})
    for name in ("players.csv", "combine_tracking.csv"):
        expected = sources.get(name, {}).get("sha256")
        if not expected or expected != source_digest(_local_file(source_dir / name)):
            raise ValueError(f"source hash mismatch for {name}")
    pfile = _local_file(source_dir / "players.csv")
    rfile = _local_file(source_dir / "combine_results.csv")
    eventfile = _local_file(combine_dir / "turn_events_RESEARCH_ONLY.csv")
    profilefile = _local_file(combine_dir / "asymmetry_RESEARCH_ONLY.csv")
    outcomes_path = _local_file(outcomes_path)
    # Fail before numerical work if required labels are absent.
    _header(outcomes_path, frozenset({"player_id", "position", "season", "outcome_name",
                                     "numerator", "denominator", "season_type"}))
    players = pd.read_csv(pfile, dtype={"nfl_id": "string"})
    results = pd.read_csv(rfile, dtype={"nfl_id": "string"})
    events = pd.read_csv(eventfile, dtype={"player_id": "string", "independent_trial_id": "string"})
    profiles = pd.read_csv(profilefile, dtype={"player_id": "string"})
    outcomes = pd.read_csv(outcomes_path, dtype={"player_id": "string"})
    panel, coverage = build_panel(players, results, events, profiles, outcomes, design)
    evaluation, predictions = evaluate_panel(panel, design)
    report = {
        "schema_version": 1,
        "authority": "RESEARCH_ONLY_NO_PROMOTION",
        "source_authentication": "USER_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED",
        "data_mode": "PRIVATE_NFL_COMPETITION_RESEARCH",
        "qualification_sha256": source_digest(mpath),
        "input_hashes": {name: source_digest(path) for name, path in {
            "players.csv": pfile, "combine_results.csv": rfile,
            "turn_events_RESEARCH_ONLY.csv": eventfile,
            "asymmetry_RESEARCH_ONLY.csv": profilefile,
            "private_rookie_outcomes.csv": outcomes_path, "study_design.json": design_path,
        }.items()},
        "design": {"sha256": design.digest(), "position": design.position,
                   "drill": design.drill, "outcome": design.outcome,
                   "baseline_features": list(design.baseline_features),
                   "primary_metric": "opportunity_capped_weighted_mae"},
        "coverage": coverage,
        "evaluation": evaluation,
        "cautions": [
            "No randomized causal inference or measured situational awareness",
            "Eligibility is conditional on a qualified bilateral estimate; check coverage/selection bias",
            "User-prepared role-specific outcome label semantics require independent review",
            "Training/holdout years fixed; 2025 may not be an untouched holdout if explored elsewhere",
            "No license or source authentication from user acknowledgments",
            "Do not commit player-level source data, panels, or predictions to GitHub",
        ],
    }
    write_private_report(output_dir, report, predictions)
    panel.to_csv(output_dir / "cohort_eligibility_PRIVATE.csv", index=False)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--combine-dir", required=True, type=Path)
    parser.add_argument("--outcomes", required=True, type=Path)
    parser.add_argument("--design", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--acknowledge-competition-data-terms", action="store_true")
    parser.add_argument("--confirm-outcome-provenance-reviewed", action="store_true")
    args = parser.parse_args()
    result = run(args.source_dir, args.combine_dir, args.outcomes, args.design,
                 args.output_dir, acknowledge_terms=args.acknowledge_competition_data_terms,
                 confirm_outcome_provenance=args.confirm_outcome_provenance_reviewed)
    print(json.dumps({"status": result["evaluation"]["status"],
                      "coverage": result["coverage"],
                      "research_only": True}, indent=2))


if __name__ == "__main__":
    main()
