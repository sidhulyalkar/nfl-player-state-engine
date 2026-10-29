"""Adversarial tests for point-in-time prospect-level evaluation: synthetic only."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from player_state_engine.research.bdb27_prediction import (
    StudyDesign, build_panel, evaluate_panel, movement_features,
)


def fixture(n=100, seed=22):
    rng = np.random.default_rng(seed)
    players = []
    results = []
    events = []
    profiles = []
    outcomes = []
    years = [2023] * 35 + [2024] * 35 + [2025] * (n-70)
    for i, year in enumerate(years):
        p = f"athlete_{i:03d}"
        asym = float(rng.normal(8, 3))
        physical = float(rng.normal(4.55, 0.16))
        players.append({"nfl_id": p, "combine_position": "DB", "draft_year": year})
        results.append({"nfl_id": p, "combine_40s": physical, "height_in": 71 + rng.normal(0, 2)})
        for attempt in range(6):
            events.append({"source_kind": "combine", "source_id": "CONE_TEST", "player_id": p,
                           "independent_trial_id": f"{p}:attempt{attempt}",
                           "entry_speed_yd_s": 4.5 + rng.normal(0, .2),
                           "speed_retention": .9 + rng.normal(0, .01),
                           "turn": "left" if attempt < 3 else "right"})
        profiles.append({"source_kind": "combine", "source_id": "CONE_TEST", "player_id": p,
                         "position": "DB", "status": "estimated", "asymmetry_pct": asym})
        rate = float(np.clip(.2 + .006 * asym + .025 * (physical-4.55) + rng.normal(0, .02), 0, 1))
        numerator = int(round(rate * 100))
        outcomes.append({"player_id": p, "position": "DB", "season": year,
                         "outcome_name": "reviewed_coverage_event_rate", "numerator": numerator,
                         "denominator": 100, "season_type": "REG"})
    design = StudyDesign(position="DB", drill="CONE_TEST", outcome="reviewed_coverage_event_rate",
                         baseline_features=("combine_40s", "height_in"),
                         min_train=25, min_test=12, bootstrap_samples=200, permutations=100)
    return tuple(pd.DataFrame(x) for x in (players, results, events, profiles, outcomes)), design


def test_synthetic_end_to_end_is_paired_research_only():
    parts, design = fixture()
    panel, coverage = build_panel(*parts, design)
    report, predictions = evaluate_panel(panel, design)
    assert coverage["position_players"] == 100
    assert coverage["complete_paired_population"] == 100
    assert report["train_players"] == 70
    assert report["test_players"] == 30
    assert report["status"] == "evaluated_research_only"
    assert set(report["model_metrics"]) == {"conventional", "simple_tracking", "directional"}
    assert len(predictions) == 30
    assert report["design_sha256"] == design.digest()
    assert 0 < report["negative_control_permutation_p"] <= 1


def test_shuffled_event_fragments_do_not_overweight_an_attempt():
    parts, design = fixture()
    e = parts[2].loc[parts[2].player_id.eq("athlete_001")].copy()
    extra = e.iloc[[0]].copy()
    extra["entry_speed_yd_s"] = 7.0
    duplicated = pd.concat([e, extra, extra], ignore_index=True)
    f = movement_features(duplicated, parts[3], drill=design.drill)
    assert len(f) == 1
    assert f.attempt_count.iloc[0] == 6
    # The median within a trial is robust to duplicate fragmentation.
    assert f.tracking_entry_speed.iloc[0] < 5.5


def test_ineligible_candidate_is_not_silently_imputed():
    parts, design = fixture()
    p, r, e, profiles, o = parts
    profiles.loc[profiles.player_id.eq("athlete_000"), "status"] = "insufficient_matched_evidence"
    panel, coverage = build_panel(p, r, e, profiles, o, design)
    assert coverage["complete_paired_population"] == 99
    assert not panel.loc[panel.player_id.eq("athlete_000"), "candidate_eligible"].iloc[0]


def test_no_estimate_when_held_out_sample_too_small():
    parts, design = fixture()
    panel, _ = build_panel(*parts, design)
    panel.loc[panel.draft_year.eq(2025), "candidate_eligible"] = False
    report, predictions = evaluate_panel(panel, design)
    assert report["status"] == "insufficient_evidence"
    assert predictions.empty
    assert "model_metrics" not in report


def test_future_2026_outcome_refused():
    parts, design = fixture()
    p, r, e, profiles, o = parts
    o.loc[o.player_id.eq("athlete_000"), "season"] = 2026
    with pytest.raises(ValueError, match="non-rookie season"):
        build_panel(p, r, e, profiles, o, design)


def test_non_reg_outcome_refused():
    parts, design = fixture()
    p, r, e, profiles, o = parts
    o.loc[o.player_id.eq("athlete_000"), "season_type"] = "POST"
    with pytest.raises(ValueError, match="nonregular"):
        build_panel(p, r, e, profiles, o, design)


def test_illegal_rates_refused():
    parts, design = fixture()
    p, r, e, profiles, o = parts
    o.loc[o.player_id.eq("athlete_000"), "numerator"] = 9999
    with pytest.raises(ValueError, match="event counts"):
        build_panel(p, r, e, profiles, o, design)


def test_ambiguous_outcome_rows_refused():
    parts, design = fixture()
    p, r, e, profiles, o = parts
    o = pd.concat([o, o.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate identity"):
        build_panel(p, r, e, profiles, o, design)


def test_forbidden_feature_and_unfrozen_holdout_refused():
    _, design = fixture()
    with pytest.raises(ValueError, match="post-draft"):
        replace(design, baseline_features=("draft_round",))
    with pytest.raises(ValueError, match="frozen"):
        replace(design, test_year=2024)
    with pytest.raises(ValueError, match="not qualified"):
        replace(design, candidate_feature="asymmetry_pct")


def test_bad_coordinates_cannot_become_gaze_or_game_feature():
    parts, design = fixture()
    with pytest.raises(ValueError, match="baseline Combine columns absent"):
        build_panel(*parts, replace(design, baseline_features=("made_up_nfl_feature",)))


def test_unexpected_holdout_player_and_cross_group_refused():
    parts, design = fixture()
    panel, _ = build_panel(*parts, design)
    panel.loc[0, "position"] = "WR"
    with pytest.raises(ValueError, match="mismatched position"):
        evaluate_panel(panel, design)


def test_report_deterministic_seed_and_heldout_permutation():
    parts, design = fixture()
    panel, _ = build_panel(*parts, design)
    a, _ = evaluate_panel(panel, design)
    b, _ = evaluate_panel(panel, design)
    assert a["negative_control_permutation_p"] == b["negative_control_permutation_p"]
    assert a["paired_player_bootstrap_95ci"] == b["paired_player_bootstrap_95ci"]


def test_no_prediction_from_tracking_after_draft():
    parts, design = fixture()
    p, r, e, profiles, outcomes = parts
    r["rookie_pressure" ] = 1.0
    with pytest.raises(ValueError, match="post-draft"):
        replace(design, baseline_features=("rookie_pressure",))


def test_private_runner_verifies_hashes_rights_and_output(tmp_path):
    import hashlib
    import json

    from scripts.run_bdb27_frozen_prediction import run

    parts, design = fixture()
    players, results, events, profiles, outcomes = parts
    sources = tmp_path / "licensed-private-source"
    qualified = tmp_path / "qualified-combine"
    destination = tmp_path / "private-results"
    sources.mkdir()
    qualified.mkdir()
    players.to_csv(sources / "players.csv", index=False)
    results.to_csv(sources / "combine_results.csv", index=False)
    (sources / "combine_tracking.csv").write_text("synthetic only\n")
    events.to_csv(qualified / "turn_events_RESEARCH_ONLY.csv", index=False)
    profiles.to_csv(qualified / "asymmetry_RESEARCH_ONLY.csv", index=False)
    outcomes_file = tmp_path / "curated_rookie_outcomes.csv"
    outcomes.to_csv(outcomes_file, index=False)
    manifest = {
        "authority": "RESEARCH_ONLY_NO_PROMOTION",
        "coordinate_handedness": "USER_DECLARED_NOT_VERIFIED",
        "sources": {
            name: {"sha256": hashlib.sha256((sources / name).read_bytes()).hexdigest()}
            for name in ("players.csv", "combine_tracking.csv")
        },
    }
    (qualified / "qualification_manifest.json").write_text(json.dumps(manifest))
    design_file = tmp_path / "design.json"
    design_file.write_text(json.dumps({"schema_version": 1, "authority": "RESEARCH_ONLY_NO_PROMOTION",
                                      **__import__("dataclasses").asdict(design)}))
    with pytest.raises(ValueError, match="acknowledgments"):
        run(sources, qualified, outcomes_file, design_file, destination)
    report = run(sources, qualified, outcomes_file, design_file, destination,
                 acknowledge_terms=True, confirm_outcome_provenance=True)
    assert report["evaluation"]["test_players"] == 30
    assert (destination / "heldout_player_predictions_PRIVATE.csv").is_file()
    assert (destination / "cohort_eligibility_PRIVATE.csv").is_file()
    assert report["authority"] == "RESEARCH_ONLY_NO_PROMOTION"
    (sources / "combine_tracking.csv").write_text("mutated after qualification")
    with pytest.raises(ValueError, match="source hash mismatch"):
        run(sources, qualified, outcomes_file, design_file, destination,
            acknowledge_terms=True, confirm_outcome_provenance=True)


def test_duplicate_player_outcome_does_not_raise_false_power():
    parts, design = fixture()
    p, r, e, profiles, o = parts
    # Duplicate the event data without generating new players or events.
    o = pd.concat([o, o.loc[o.player_id.eq("athlete_001")]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate identity"):
        build_panel(p, r, e, profiles, o, design)
