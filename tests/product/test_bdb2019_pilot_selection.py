"""Offline, position-free reproducible selection of the 12-play research pilot."""
from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.select_bdb2019_pilot import select_pilot, validate_selection


def catalog() -> dict:
    ids = ["938", "2756", *(str(100 + i) for i in range(30))]
    plays = [
        {
            "game_id": "2017090700",
            "play_id": pid,
            "source_rows": 25 + i * 8,
            "recorded_frames": 4 + i * 3,
            "missing_frame_ids": (i * 7) % 11,
            "coverage_ratio": round((4 + i * 3) / (4 + i * 3 + (i * 7) % 11), 5),
            "unrenderable_position_rows": i % 7,
            "ball_recorded_frames": (4 + i * 3) if i % 4 else 0,
            "unique_players": 2 + (i % 20),
            "max_players_per_frame": 2 + (i % 20),
            "source_events": {"ball_snap": [1]} if i % 2 else {},
        }
        for i, pid in enumerate(ids)
    ]
    return {
        "schema_version": 1,
        "data_mode": "HISTORICAL_RESEARCH_METADATA_ONLY",
        "qualification_status": "OFFICIAL_TRACKING_BYTES_AUDITED_VIDEO_PENDING",
        "game_id": "2017090700",
        "positions_included": False,
        "source_video_alignment_verified": False,
        "model_training_authorized": False,
        "commercial_reuse_authorized": False,
        "license_declaration": "REVIEWED_EXAMPLE",
        "source_sha256": "a" * 64,
        "play_count": len(plays),
        "plays": plays,
    }


def test_diversified_pilot_is_repeatable_independent_of_catalog_order() -> None:
    a = catalog()
    plan = select_pilot(a, "REVIEWED_EXAMPLE")
    assert plan["qualification"] == "PLAN_ONLY_NOT_EXECUTED"
    assert plan["play_count"] == 12
    assert len(set(plan["selected_play_ids"])) == 12
    assert plan["selected_play_ids"][:2] == ["938", "2756"]
    assert plan["source_file_sha256"] == "a" * 64
    assert set(plan["selection_reason_by_play"]) == set(plan["selected_play_ids"])
    assert plan["model_training_authorized"] is False
    a["plays"].reverse()
    assert select_pilot(a, "REVIEWED_EXAMPLE") == plan
    assert validate_selection(plan, license_id="REVIEWED_EXAMPLE",
                              source_sha256="a" * 64) == plan["selected_play_ids"]


@pytest.mark.parametrize("change", [
    lambda x: x.update(qualification_status="NONCANONICAL"),
    lambda x: x.update(positions_included=True),
    lambda x: x.update(source_video_alignment_verified=True),
    lambda x: x.update(model_training_authorized=True),
    lambda x: x.update(source_sha256="not_a_hash"),
    lambda x: x.update(license_declaration="UNREVIEWED"),
    lambda x: x.update(play_count=13),
    lambda x: x["plays"].append(x["plays"][0]),
    lambda x: x["plays"][0].update(coverage_ratio=1.2),
    lambda x: x["plays"][0].update(game_id="2017091000"),
    lambda x: x["plays"][0].update(ball_recorded_frames=999),
])
def test_noncanonical_catalogs_cannot_choose_official_pilot(change) -> None:
    value = catalog()
    change(value)
    with pytest.raises(ValueError):
        select_pilot(value, "REVIEWED_EXAMPLE")


def test_reference_plays_are_required_and_no_rights_are_inferred() -> None:
    value = catalog()
    value["plays"] = [p for p in value["plays"] if p["play_id"] != "938"]
    value["play_count"] = len(value["plays"])
    with pytest.raises(ValueError, match="reference play"):
        select_pilot(value, "REVIEWED_EXAMPLE")
    with pytest.raises(ValueError, match="canonical metadata-only"):
        select_pilot(catalog(), "WRONG_SOURCE_TERMS")


@pytest.mark.parametrize("change", [
    lambda x: x.update(source_file_sha256="b" * 64),
    lambda x: x.update(qualification="ACTUALLY_RAN"),
    lambda x: x.update(model_training_authorized=True),
    lambda x: x.update(play_count=11),
    lambda x: x["selected_play_ids"].__setitem__(0, "../938"),
    lambda x: x["selected_play_ids"].__setitem__(0, x["selected_play_ids"][1]),
])
def test_export_selection_fails_closed_on_unauthorized_edits(change) -> None:
    plan = deepcopy(select_pilot(catalog(), "REVIEWED_EXAMPLE"))
    change(plan)
    with pytest.raises(ValueError):
        validate_selection(plan, license_id="REVIEWED_EXAMPLE",
                           source_sha256="a" * 64)


def test_changed_hash_and_license_cannot_be_reused() -> None:
    plan = select_pilot(catalog(), "REVIEWED_EXAMPLE")
    with pytest.raises(ValueError, match="source/rights"):
        validate_selection(plan, license_id="REVIEWED_EXAMPLE",
                           source_sha256="c" * 64)
    with pytest.raises(ValueError, match="source/rights"):
        validate_selection(plan, license_id="CHANGED_TERMS",
                           source_sha256="a" * 64)
