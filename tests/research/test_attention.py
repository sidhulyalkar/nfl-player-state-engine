from __future__ import annotations

import pytest

from player_state_engine.research.head_attention import (
    CandidateTarget,
    HeadObservation,
    head_target_evidence,
)
from player_state_engine.research.position_profiles import DIMENSIONS, available_dimensions


def pose(**updates) -> HeadObservation:
    data = {"head_yaw_deg": 20.0, "torso_yaw_deg": 0.0,
            "head_pose_confidence": 0.95, "head_yaw_uncertainty_deg": 9.0,
            "source_id": "licensed_synthetic_pose"}
    data.update(updates)
    return HeadObservation(**data)


def test_head_alignment_candidate_scores_are_not_gaze_or_awareness() -> None:
    r = head_target_evidence(pose(), [CandidateTarget("receiver", 20), CandidateTarget("sideline", 120)])
    assert r["status"] == "candidate_evidence_only"
    assert r["mode"] == "HEAD_ALIGNMENT_PROXY"
    assert not r["is_measured_gaze"] and not r["is_awareness_measure"]
    assert r["scores"]["receiver"] > r["scores"]["sideline"]
    assert sum(r["scores"].values()) + r["unknown"] == pytest.approx(1.0)
    assert r["unknown"] > 0
    assert r["head_relative_torso_deg"] == 20.0


def test_no_head_pose_abstains_even_when_scene_has_strong_target() -> None:
    r = head_target_evidence(pose(head_yaw_deg=None), [CandidateTarget("receiver", 20)])
    assert r["status"] == "abstain"
    assert r["unknown"] == 1.0


def test_low_confidence_abstains_and_never_uses_scene_as_truth() -> None:
    r = head_target_evidence(pose(head_pose_confidence=0.4), [CandidateTarget("ball", 20)])
    assert r["unknown"] == 1.0


def test_angular_wrap_and_calibrated_offset() -> None:
    r = head_target_evidence(pose(head_yaw_deg=179, torso_yaw_deg=-179,
        calibration_verified=True, calibrated_eye_offset_deg=10),
        [CandidateTarget("target", -171)])
    assert r["head_relative_torso_deg"] == -2
    assert r["mode"] == "CALIBRATED_GAZE_CANDIDATE_INFERENCE"
    assert not r["is_measured_gaze"]


def test_false_calibration_refused() -> None:
    with pytest.raises(ValueError, match="calibration"):
        pose(calibration_verified=True)


def test_duplicate_target_refused() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        head_target_evidence(pose(), [CandidateTarget("same", 20), CandidateTarget("same", 30)])


def test_position_profile_requires_actual_sources_and_has_no_false_scores() -> None:
    assert set(DIMENSIONS) == {"DB", "WR", "TE", "OL", "DL"}
    profile = available_dimensions("DB", {"tracking"})
    assert profile[0]["eligible"]
    assert not profile[1]["eligible"]
    assert "assignment_labels" in profile[1]["missing_sources"]
    assert not profile[2]["eligible"]
    assert all("score" not in item for item in profile)
