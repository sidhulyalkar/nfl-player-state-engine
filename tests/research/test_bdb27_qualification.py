"""No actual competition bytes. Adversarial official-format source fixtures."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from player_state_engine.research.bdb27_qualification import (
    QualificationConfig,
    canonical_combine,
    eligibility_by_drill,
    qualify_directory,
)
from player_state_engine.research.bilateral import asymmetry_profiles, extract_turn_events


def players() -> pd.DataFrame:
    return pd.DataFrame({"nfl_id": [1001, 1002], "combine_position": ["DB", "WR"],
                         "draft_year": [2023, 2024]})


def attempt(attempt_id: int = 1, *, player_id: int = 1001,
            side: int = 1, broken: bool = False, glitch: bool = False) -> pd.DataFrame:
    xy = [(i * 0.5, 24.0) for i in range(6)]
    xy += [(2.5, 24.0 + side * j * 0.4) for j in range(1, 7)]
    seconds = np.arange(len(xy)) / 10.0
    if broken:
        seconds[6:] += 0.4
    if glitch:
        xy[6] = (400, 400)
    times = pd.Timestamp("2023-03-01", tz="UTC") + pd.to_timedelta(seconds, unit="s")
    return pd.DataFrame({
        "nfl_id": player_id, "entity_type": "PLAYER", "drill_type": "SKILL_DRILLS_DB",
        "drill_name": "BACKPEDAL", "attempt": attempt_id,
        "event_id": f"e{attempt_id}", "time": times.astype(str),
        "x": [p[0] for p in xy], "y": [p[1] for p in xy],
    })


def test_source_attempt_is_independent_unit_after_gap_splitting():
    raw = pd.concat([attempt(1, broken=True), attempt(2)])
    canonical, trials, qa = canonical_combine(raw, players(), QualificationConfig(1))
    assert len(trials) == 2
    assert canonical.independent_trial_id.nunique() == 1
    assert len(trials) == 2
    assert qa["rejected_intervals"] == 1
    assert qa["discarded_short_segment_frames"] > 0
    assert len(canonical) < len(raw)
    assert len(extract_turn_events(canonical)) == 1


def test_symmetry_direction_is_sensitive_to_declared_reflection():
    c1, _, _ = canonical_combine(attempt(), players(), QualificationConfig(1))
    c2, _, _ = canonical_combine(attempt(), players(), QualificationConfig(-1))
    assert extract_turn_events(c1).iloc[0].turn == "left"
    assert extract_turn_events(c2).iloc[0].turn == "right"


def test_duplicate_timestamps_fail_closed():
    bad = attempt()
    bad.loc[3, "time"] = bad.loc[2, "time"]
    with pytest.raises(ValueError, match="duplicate timestamps"):
        canonical_combine(bad, players(), QualificationConfig(1))


def test_teleport_is_rejected_not_a_turn():
    out, _, qa = canonical_combine(attempt(glitch=True), players(), QualificationConfig(1))
    assert qa["rejected_teleports"] >= 1
    assert out.empty or len(extract_turn_events(out)) == 0


def test_unknown_player_fails_without_inner_join_selection_bias():
    with pytest.raises(ValueError, match="absent"):
        canonical_combine(attempt(player_id=5555), players(), QualificationConfig(1))


def test_invalid_cohort_and_duplicate_players_fail():
    dup = pd.concat([players(), players().iloc[:1]])
    with pytest.raises(ValueError, match="duplicated"):
        canonical_combine(attempt(), dup, QualificationConfig(1))
    future = players().assign(draft_year=2029)
    with pytest.raises(ValueError, match="unexpected draft cohort"):
        canonical_combine(attempt(), future, QualificationConfig(1))


def test_whole_attempt_replication_not_split_counted():
    raw = pd.concat([attempt(i, side=1) for i in range(4)] +
                    [attempt(i+4, side=-1) for i in range(4)], ignore_index=True)
    canon, trials, _ = canonical_combine(raw, players(), QualificationConfig(1))
    events = extract_turn_events(canon)
    eligible = eligibility_by_drill(events, trials)
    assert eligible.iloc[0].players_with_estimable_bilateral_asymmetry == 1
    profile = asymmetry_profiles(events, bootstrap_samples=120)
    assert profile.iloc[0].segments_left == 4
    assert profile.iloc[0].segments_right == 4
    assert profile.iloc[0].status == "estimated"
    # Repeating the same trial across fragments cannot inflate effective n.
    corrupted = events.copy()
    corrupted.loc[:, "independent_trial_id"] = "single-trial"
    abstain = asymmetry_profiles(corrupted, bootstrap_samples=100)
    assert abstain.iloc[0].status == "insufficient_matched_evidence"


def test_eligibility_rejects_one_direction():
    canon, trials, _ = canonical_combine(pd.concat([attempt(i) for i in range(5)]),
                                         players(), QualificationConfig(1))
    result = eligibility_by_drill(extract_turn_events(canon), trials)
    assert result.iloc[0].players_with_estimable_bilateral_asymmetry == 0


def test_qualified_local_output_hashes_and_observability(tmp_path: Path):
    src = tmp_path / "source"
    src.mkdir()
    players().to_csv(src / "players.csv", index=False)
    pd.concat([attempt(i, side=1 if i % 2 == 0 else -1) for i in range(8)]).to_csv(
        src / "combine_tracking.csv", index=False)
    out = tmp_path / "audit"
    with pytest.raises(ValueError, match="acknowledgement"):
        qualify_directory(src, out, QualificationConfig(1))
    r = qualify_directory(src, out, QualificationConfig(1), source_rights_acknowledged=True)
    assert r["audit"]["unique_trials"] == 8
    assert r["audit"]["estimated_profiles"] == 1
    assert r["source_status"] == "USER_PROVIDED_CSVS_NOT_INDEPENDENTLY_AUTHENTICATED"
    assert r["coordinate_handedness"] == "USER_DECLARED_NOT_VERIFIED"
    assert (out / "eligibility_by_drill.csv").is_file()
    assert json.loads((out / "qualification_manifest.json").read_text())["sources"]["players.csv"]["sha256"]
    assert not (src / "qualification_manifest.json").exists()
    with pytest.raises(ValueError, match="outside licensed source directory"):
        qualify_directory(src, src / "reports", QualificationConfig(1), source_rights_acknowledged=True)


def test_missing_header_and_symlinks_fail_closed(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    players().to_csv(source / "players.csv", index=False)
    attempt().drop(columns="drill_name").to_csv(source / "combine_tracking.csv", index=False)
    with pytest.raises(ValueError, match="invalid combine_tracking.csv header"):
        qualify_directory(source, tmp_path / "audit", QualificationConfig(1),
                          source_rights_acknowledged=True)
    (source / "combine_tracking.csv").unlink()
    real = tmp_path / "raw.csv"
    attempt().to_csv(real, index=False)
    (source / "combine_tracking.csv").symlink_to(real)
    with pytest.raises(ValueError, match="symlinked"):
        qualify_directory(source, tmp_path / "audit", QualificationConfig(1),
                          source_rights_acknowledged=True)
