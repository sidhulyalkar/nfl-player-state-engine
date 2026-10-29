"""Explicit observability contract for future position-specific decision profiles."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProfileDimension:
    name: str
    question: str
    required_data: tuple[str, ...]
    evidence_level: str


DIMENSIONS: dict[str, tuple[ProfileDimension, ...]] = {
    "DB": (
        ProfileDimension("directional_reversal", "Can direction changes be reproduced on both sides?", ("tracking",), "kinematic_proxy"),
        ProfileDimension("coverage_leverage", "Is correct tactical leverage maintained?", ("full_scene", "assignment_labels"), "requires_context"),
        ProfileDimension("pre_break_visual_sampling", "Which threats appear to be visually sampled?", ("licensed_video", "calibrated_gaze", "full_scene"), "requires_validation"),
    ),
    "WR": (
        ProfileDimension("turn_reacceleration", "How does speed recover after route-like cuts?", ("tracking",), "kinematic_proxy"),
        ProfileDimension("route_deadline", "Does the player arrive at the coached timing landmark?", ("tracking", "route_assignment", "target_timing"), "requires_context"),
    ),
    "TE": (
        ProfileDimension("transition_recovery", "How efficiently are sequential movement phases completed?", ("tracking",), "kinematic_proxy"),
        ProfileDimension("blocking_choice", "Was the correct blocking threat selected?", ("full_scene", "assignment_labels"), "requires_context"),
    ),
    "OL": (
        ProfileDimension("lateral_reversal", "How does lateral redirection vary with demand and direction?", ("tracking",), "kinematic_proxy"),
        ProfileDimension("passoff_recognition", "Was a changing protection threat identified?", ("full_scene", "assignment_labels", "licensed_video"), "requires_validation"),
    ),
    "DL": (
        ProfileDimension("curved_rush_retention", "How is speed retained during path changes?", ("tracking",), "kinematic_proxy"),
        ProfileDimension("blocker_adaptation", "Was a rush adjustment productive against the blocker?", ("full_scene", "outcome_labels"), "requires_context"),
    ),
}


def available_dimensions(position: str, available_sources: set[str]) -> list[dict]:
    """Return dimensions with explicit missing-evidence conditions; no skill scores."""
    if position not in DIMENSIONS:
        raise ValueError("unsupported position group")
    return [
        {"name": item.name, "question": item.question,
         "evidence_level": item.evidence_level,
         "eligible": set(item.required_data).issubset(available_sources),
         "missing_sources": sorted(set(item.required_data) - available_sources)}
        for item in DIMENSIONS[position]
    ]
