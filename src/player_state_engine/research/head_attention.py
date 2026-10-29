"""Geometry-only, *non-cognitive* attention evidence from externally estimated head pose.

This is NOT a video decoder, gaze detector, or proof of player awareness.
Video ingestion is intentionally excluded pending a licensed, independently
calibrated multi-view dataset. No identities, injury or mental-state inferences.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite


def _wrap(degrees: float) -> float:
    return (degrees + 180.0) % 360.0 - 180.0


@dataclass(frozen=True)
class CandidateTarget:
    """Scene target bearing from +X toward +Y in canonical fixed-field axes."""

    target_id: str
    bearing_deg: float

    def __post_init__(self) -> None:
        if not self.target_id or not isfinite(self.bearing_deg):
            raise ValueError("target requires an ID and finite geometric bearing")


@dataclass(frozen=True)
class HeadObservation:
    """External pose estimate and evidence quality, not face/gaze ground truth."""

    head_yaw_deg: float | None
    torso_yaw_deg: float | None
    head_pose_confidence: float
    head_yaw_uncertainty_deg: float
    source_id: str
    calibrated_eye_offset_deg: float | None = None
    calibration_verified: bool = False

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id required for evidence provenance")
        if not isfinite(self.head_pose_confidence) or not 0 <= self.head_pose_confidence <= 1:
            raise ValueError("head_pose_confidence must lie in [0, 1]")
        if not isfinite(self.head_yaw_uncertainty_deg) or self.head_yaw_uncertainty_deg < 1:
            raise ValueError("head_yaw_uncertainty_deg must be >= 1")
        if self.head_yaw_deg is not None and not isfinite(self.head_yaw_deg):
            raise ValueError("nonfinite head pose")
        if self.torso_yaw_deg is not None and not isfinite(self.torso_yaw_deg):
            raise ValueError("nonfinite torso pose")
        if self.calibrated_eye_offset_deg is not None and not isfinite(self.calibrated_eye_offset_deg):
            raise ValueError("nonfinite eye calibration")
        if self.calibration_verified and self.calibrated_eye_offset_deg is None:
            raise ValueError("verified calibration requires measured offset")


def head_target_evidence(
    pose: HeadObservation,
    targets: list[CandidateTarget],
    *,
    minimum_confidence: float = 0.75,
    angular_spread_floor_deg: float = 15.0,
    unknown_weight: float = 0.5,
) -> dict:
    """Normalized head-alignment evidence over proposed targets plus UNKNOWN.

    These are heuristic normalized scores, NOT calibrated gaze probabilities.
    Scene priors must never turn missing head pose into asserted attention.
    """
    if not 0 < minimum_confidence <= 1 or angular_spread_floor_deg <= 0 or unknown_weight <= 0:
        raise ValueError("invalid evidence settings")
    if len({t.target_id for t in targets}) != len(targets):
        raise ValueError("duplicate target IDs")
    head_relative_torso = None
    if pose.head_yaw_deg is not None and pose.torso_yaw_deg is not None:
        head_relative_torso = _wrap(pose.head_yaw_deg - pose.torso_yaw_deg)
    result = {
        "source_id": pose.source_id,
        "mode": "HEAD_ALIGNMENT_PROXY",
        "provenance": "unvalidated_geometric_inference",
        "is_measured_gaze": False,
        "is_awareness_measure": False,
        "head_relative_torso_deg": head_relative_torso,
        "scores": {t.target_id: 0.0 for t in targets},
        "unknown": 1.0,
        "status": "abstain",
    }
    if pose.head_yaw_deg is None or pose.head_pose_confidence < minimum_confidence or not targets:
        return result
    # A verified eye-head calibration can improve geometry, but this still does
    # not establish that the target was actually fixated or cognitively noticed.
    center = pose.head_yaw_deg
    if pose.calibration_verified and pose.calibrated_eye_offset_deg is not None:
        center += pose.calibrated_eye_offset_deg
        result["mode"] = "CALIBRATED_GAZE_CANDIDATE_INFERENCE"
    spread = max(angular_spread_floor_deg, pose.head_yaw_uncertainty_deg)
    scores = {
        target.target_id: exp(-0.5 * (_wrap(target.bearing_deg - center) / spread) ** 2)
        * pose.head_pose_confidence
        for target in targets
    }
    # Never remove UNKNOWN: out-of-frame, peripheral vision, eye-in-head
    # rotation, helmet motion, and unsuitable target lists remain possible.
    unknown = unknown_weight + 1.0 - pose.head_pose_confidence
    denominator = sum(scores.values()) + unknown
    result.update({
        "scores": {name: float(weight / denominator) for name, weight in scores.items()},
        "unknown": float(unknown / denominator),
        "status": "candidate_evidence_only",
    })
    return result
