from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))
import capture_prospective_availability_snapshot as capture  # noqa: E402


def _schedule_bytes() -> bytes:
    return (
        b"game_id,season,game_type,week,gameday,gametime,away_team,home_team\n"
        b"2026_01_A_B,2026,REG,1,2026-09-13,13:00,A,B\n"
    )


def _injury_bytes() -> bytes:
    return (
        b"season,week,gsis_id,full_name,team,position,practice_status,report_status,"
        b"report_primary_injury,date_modified\n"
        b"2026,1,p1,Player One,A,WR,Limited Participation in Practice,Questionable,"
        b"Hamstring,2026-09-12T20:00:00Z\n"
        b"2026,1,p1,Player One,A,WR,Did Not Participate in Practice,Questionable,"
        b"Hamstring,2026-09-11T20:00:00Z\n"
    )


def _build(collected_at: str) -> tuple[pd.DataFrame, dict[str, object]]:
    return capture.build_snapshot(
        _injury_bytes(),
        _schedule_bytes(),
        injury_url="https://example.test/injuries_2026.csv",
        schedule_url="https://example.test/commit/games.csv",
        schedule_commit="abc123",
        season=2026,
        week=1,
        collected_at_utc=collected_at,
    )


def test_collection_time_before_cutoff_is_usable_and_latest_row_is_selected() -> None:
    # 13:00 Eastern in September is 17:00 UTC; the registered cutoff is 15:30 UTC.
    snapshot, manifest = _build("2026-09-13T15:00:00Z")

    assert len(snapshot) == 1
    row = snapshot.iloc[0]
    assert row["player_id"] == "p1"
    assert row["practice_status"] == "limited participation in practice"
    assert row["report_status"] == "questionable"
    assert bool(row["usable_before_cutoff"])
    assert str(row["source_collected_at_utc"]) == "2026-09-13 15:00:00+00:00"
    assert manifest["usable_before_cutoff_rows"] == 1
    assert manifest["contains_player_outcomes"] is False
    assert manifest["production_feature_enabled"] is False


def test_collection_after_cutoff_is_retained_for_audit_but_not_usable() -> None:
    snapshot, manifest = _build("2026-09-13T16:00:00Z")

    assert len(snapshot) == 1
    assert not bool(snapshot.iloc[0]["usable_before_cutoff"])
    assert manifest["usable_before_cutoff_rows"] == 0


def test_publisher_date_does_not_backdate_evidence_availability() -> None:
    snapshot, _ = _build("2026-09-13T16:00:00Z")
    row = snapshot.iloc[0]

    assert pd.Timestamp(row["source_date_modified"]) < pd.Timestamp(row["prediction_cutoff"])
    assert pd.Timestamp(row["source_collected_at_utc"]) > pd.Timestamp(row["prediction_cutoff"])
    assert not bool(row["usable_before_cutoff"])


def test_snapshot_manifest_content_addresses_mutable_source_bytes() -> None:
    snapshot, manifest = _build("2026-09-13T15:00:00Z")

    injury_source = manifest["injury_source"]
    schedule_source = manifest["schedule_source"]
    assert injury_source["sha256"] == capture._sha256_bytes(_injury_bytes())
    assert injury_source["bytes"] == len(_injury_bytes())
    assert schedule_source["sha256"] == capture._sha256_bytes(_schedule_bytes())
    assert schedule_source["commit"] == "abc123"
    assert snapshot["source_sha256"].nunique() == 1


def test_persist_snapshot_is_immutable(tmp_path: Path) -> None:
    snapshot, manifest = _build("2026-09-13T15:00:00Z")
    destination = capture.persist_snapshot(
        snapshot,
        manifest,
        _injury_bytes(),
        output_root=tmp_path,
    )

    assert (destination / "injuries_source.csv").read_bytes() == _injury_bytes()
    assert (destination / "availability_snapshot.csv").is_file()
    assert (destination / "manifest.json").is_file()
    with pytest.raises(FileExistsError):
        capture.persist_snapshot(
            snapshot,
            manifest,
            _injury_bytes(),
            output_root=tmp_path,
        )