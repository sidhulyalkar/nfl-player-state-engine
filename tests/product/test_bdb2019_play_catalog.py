from __future__ import annotations

import csv
from pathlib import Path

import pytest

from player_state_engine.product.bdb2019_play_catalog import (
    scan_bdb2019_play_catalog,
    write_play_catalog,
)


def _fixture(path: Path, rows: list[dict[str, str]] | None = None) -> Path:
    fields = [
        "gameId", "playId", "frame.id", "nflId", "team", "x", "y", "event",
    ]
    if rows is None:
        rows = [
            dict(zip(fields, vals))
            for vals in [
                ("2017090700", "938", "1", "11", "away", "40", "21", "ball_snap"),
                ("2017090700", "938", "1", "NA", "ball", "40", "21", "ball_snap"),
                ("2017090700", "938", "3", "11", "away", "42", "22", "touchdown"),
                ("2017090700", "938", "3", "NA", "ball", "42", "22", "touchdown"),
                ("2017090700", "2756", "1", "22", "home", "45", "21", "ball_snap"),
                ("2017090700", "2756", "2", "22", "home", "45", "-0.59", "NA"),
                ("2017090700", "2756", "2", "NA", "ball", "42", "NA", "tackle"),
            ]
        ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _scan(path: Path, **kwargs: object) -> dict:
    return scan_bdb2019_play_catalog(
        path,
        license_acknowledged=True,
        license_identifier="synthetic-fixture-only",
        require_official_blob=False,
        **kwargs,
    )


def test_fixture_catalog_preserves_source_events_and_audits_positions(tmp_path: Path) -> None:
    src = _fixture(tmp_path / "tracking.csv")
    catalog = _scan(src)
    assert catalog["play_count"] == 2
    assert catalog["source_rows"] == 7
    assert catalog["positions_included"] is False
    assert catalog["qualification_status"] == "SYNTHETIC_OR_NONCANONICAL_FIXTURE_ONLY"
    p, q = catalog["plays"]
    assert p["play_id"] == "938"
    assert p["recorded_frames"] == 2 and p["missing_frame_ids"] == 1
    assert p["source_events"]["ball_snap"] == [1]
    assert p["source_events"]["touchdown"] == [3]
    assert p["unique_players"] == 1 and p["ball_recorded_frames"] == 2
    assert q["play_id"] == "2756"
    assert q["off_field_rows"] == 1
    assert q["missing_xy_rows"] == 1
    assert q["affected_source_frame_ids"] == [2]
    written = write_play_catalog(catalog, tmp_path / "out" / "catalog.json")
    contents = written.read_text()
    assert '"positions_included": false' in contents
    assert '"x":' not in contents and '"y":' not in contents


def test_source_hash_required_for_official_authority(tmp_path: Path) -> None:
    src = _fixture(tmp_path / "tracking.csv")
    with pytest.raises(ValueError, match="differs from pinned official NFL"):
        scan_bdb2019_play_catalog(
            src, license_acknowledged=True, license_identifier="fixture",
        )


def test_tracking_catalog_rejects_duplicate_identity_and_mixed_games(tmp_path: Path) -> None:
    src = _fixture(tmp_path / "tracking.csv")
    with src.open("a", encoding="utf-8") as stream:
        stream.write("2017090700,938,1,11,away,50,21,NA\n")
    with pytest.raises(ValueError, match="Duplicate source frame"):
        _scan(src)
    src = _fixture(tmp_path / "tracking.csv")
    with src.open("a", encoding="utf-8") as stream:
        stream.write("2017090701,999,1,99,away,50,21,NA\n")
    with pytest.raises(ValueError, match="cannot mix NFL game"):
        _scan(src)


def test_catalog_rejects_unacknowledged_terms_and_unbounded_input(tmp_path: Path) -> None:
    src = _fixture(tmp_path / "tracking.csv")
    with pytest.raises(ValueError, match="Source terms"):
        scan_bdb2019_play_catalog(src, require_official_blob=False)
    with pytest.raises(ValueError, match="max_rows"):
        _scan(src, max_rows=2)


def test_catalog_rejects_wrong_player_team_even_if_off_field(tmp_path: Path) -> None:
    src = _fixture(tmp_path / "tracking.csv")
    text = src.read_text().replace("2756,2,22,home", "2756,2,22,ball")
    src.write_text(text)
    with pytest.raises(ValueError, match="tracked player must carry"):
        _scan(src)
