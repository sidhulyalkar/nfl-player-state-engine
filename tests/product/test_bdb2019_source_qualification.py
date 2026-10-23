"""Synthetic source-contract tests, never disguised as actual NFL tracking."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from player_state_engine.product.bdb2019_source_qualification import (
    SOURCE_FILES,
    file_identifiers,
    qualify_bdb2019_play,
    verify_file_identities,
    write_qualification_report,
)


def _csv(path: Path, columns: list[str], records: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)


def fixture_source(tmp_path: Path) -> tuple[Path, dict[str, tuple[str, str, int]]]:
    game = {
        "gameId": "2017090700",
        "season": "2017",
        "week": "1",
        "homeTeamAbbr": "NE",
        "visitorTeamAbbr": "KC",
    }
    play = {
        "gameId": "2017090700",
        "playId": "938",
        "quarter": "1",
        "down": "3",
        "yardsToGo": "7",
        "possessionTeam": "KC",
        "offenseFormation": "SHOTGUN",
        "personnel.offense": "1 RB, 2 TE, 2 WR",
    }
    tracking = [
        {
            "gameId": "2017090700", "playId": "938",
            "frame.id": str(frame), "nflId": player,
            "team": team, "x": str(x), "y": str(y),
            "s": "2.5", "event": "ball_snap" if frame == 1 else "NA",
            "displayName": "Synthetic player" if player else "football",
            "jerseyNumber": "81" if player else "NA",
        }
        for frame, player, team, x, y in [
            (1, "11", "away", 40.0, 21.0),
            (1, "22", "home", 43.0, 21.0),
            (1, "NA", "football", 40.0, 21.0),
            (3, "11", "away", 43.0, 22.0),
            (3, "22", "home", 45.0, 22.0),
            (3, "NA", "football", 44.0, 22.0),
        ]
    ]
    _csv(tmp_path / "games.csv", list(game), [game])
    _csv(tmp_path / "plays.csv", list(play), [play])
    _csv(tmp_path / SOURCE_FILES["tracking"][0], list(tracking[0]), tracking)
    expected = {
        kind: (
            filename,
            file_identifiers(tmp_path / filename)["git_blob_sha1"],
            file_identifiers(tmp_path / filename)["bytes"],
        )
        for kind, (filename, _, _) in SOURCE_FILES.items()
    }
    return tmp_path, expected


def _qualify(path: Path, expected: dict, **override: object) -> tuple[dict, dict]:
    return qualify_bdb2019_play(
        path, play_id="938",
        expectations=expected,
        license_acknowledged=True,
        license_identifier="test-fixture-contract-not-an-NFL-license",
        **override,
    )


def _rehashed(path: Path) -> dict[str, tuple[str, str, int]]:
    return {
        kind: (filename, file_identifiers(path / filename)["git_blob_sha1"], (path / filename).stat().st_size)
        for kind, (filename, _, _) in SOURCE_FILES.items()
    }


def test_fixture_verified_metadata_joins_not_inferred_from_coordinates(tmp_path: Path) -> None:
    path, expected = fixture_source(tmp_path)
    report, replay = _qualify(path, expected)
    assert report["qualification_status"] == "SYNTHETIC_OR_NONCANONICAL_FIXTURE_ONLY"
    assert report["source_video_alignment_verified"] is False
    assert report["play"]["possession_team"] == "KC"
    assert report["play"]["offense_side_verified_from_metadata"] == "away"
    assert report["game"]["home_team"] == "NE"
    assert report["game"]["away_team"] == "KC"
    assert replay["offense_side"] == "away"
    assert replay["frames"][0]["players"][0]["side"] == "offense"
    assert replay["frames"][0]["players"][1]["side"] == "defense"
    assert report["tracking"]["missing_frame_count"] == 1
    assert report["tracking"]["frame_coverage"] == pytest.approx(2 / 3)
    assert report["tracking"]["source_labeled_snap_frames"] == [1]
    assert report["tracking"]["ball_observed_frames"] == 2
    assert report["tracking"]["unique_player_ids"] == 2
    out = write_qualification_report(report, tmp_path / "out" / "report.json")
    assert json.loads(out.read_text())["source_video_alignment_verified"] is False


def test_pinned_real_source_rejects_synthetic_fixture(tmp_path: Path) -> None:
    path, _ = fixture_source(tmp_path)
    with pytest.raises(ValueError, match="pinned official Git blob"):
        verify_file_identities(path)
    with pytest.raises(ValueError, match="pinned official Git blob"):
        qualify_bdb2019_play(
            path,
            license_acknowledged=True,
            license_identifier="fixture-only",
        )


def test_source_mutation_rejected_before_parsing_or_reporting(tmp_path: Path) -> None:
    path, expected = fixture_source(tmp_path)
    with (path / "games.csv").open("a", encoding="utf-8") as stream:
        stream.write("untrusted extra row\n")
    with pytest.raises(ValueError, match="games source bytes"):
        _qualify(path, expected)


def test_metadata_possession_mismatch_fails_closed(tmp_path: Path) -> None:
    path, _ = fixture_source(tmp_path)
    plays = path / "plays.csv"
    lines = plays.read_text()
    plays.write_text(lines.replace(",KC,SHOTGUN", ",ARI,SHOTGUN"))
    with pytest.raises(ValueError, match="Possession team cannot be reconciled"):
        _qualify(path, _rehashed(path))


def test_duplicate_game_and_play_metadata_rejected(tmp_path: Path) -> None:
    path, _ = fixture_source(tmp_path)
    with (path / "plays.csv").open("a", encoding="utf-8") as stream:
        stream.write((path / "plays.csv").read_text().splitlines()[1] + "\n")
    with pytest.raises(ValueError, match="Duplicate metadata key"):
        _qualify(path, _rehashed(path))


def test_invalid_tracking_sample_blocks_qualification(tmp_path: Path) -> None:
    path, _ = fixture_source(tmp_path)
    track = path / SOURCE_FILES["tracking"][0]
    txt = track.read_text()
    track.write_text(txt.replace(",43.0,22.0,", ",134.0,22.0,", 1))
    # The full qualifier opts explicitly into audited omission to preserve a
    # real play with source frames extending outside the playing field.
    report, replay = _qualify(path, _rehashed(path))
    quality = report["tracking"]["position_quality"]
    assert quality["omitted_off_field_position_rows"] == 1
    assert quality["omitted_missing_position_rows"] == 0
    assert quality["affected_source_frame_ids"] == [3]
    assert quality["never_clamped_or_interpolated"] is True
    assert replay["frames"][1]["players"][0]["nfl_id"] == "22"
    assert all(p["x"] <= 120 for frame in replay["frames"] for p in frame["players"])


def test_missing_snap_and_ball_are_flags_not_fabricated(tmp_path: Path) -> None:
    path, _ = fixture_source(tmp_path)
    tracking = path / SOURCE_FILES["tracking"][0]
    with tracking.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = list(reader.fieldnames or ())
        rows = [row for row in reader if row["nflId"] != "NA"]
    for row in rows:
        row["event"] = "NA"
    _csv(tracking, columns, rows)
    report, replay = _qualify(path, _rehashed(path))
    assert report["tracking"]["source_labeled_snap_frames"] == []
    assert report["tracking"]["ball_observed_frames"] == 0
    assert len(report["warnings"]) >= 2
    assert replay["frames"][0]["ball"] is None


def test_explicit_terms_declaration_required(tmp_path: Path) -> None:
    path, expected = fixture_source(tmp_path)
    with pytest.raises(ValueError, match="source terms acknowledgement"):
        qualify_bdb2019_play(path, expectations=expected)
    with pytest.raises(ValueError, match="source terms acknowledgement"):
        qualify_bdb2019_play(
            path, expectations=expected, license_acknowledged=True, license_identifier=""
        )


def test_off_field_player_keeps_play_events_and_reports_exclusion(
    tmp_path: Path,
) -> None:
    path, _ = fixture_source(tmp_path)
    tracking = path / SOURCE_FILES["tracking"][0]
    with tracking.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = list(reader.fieldnames or ())
        rows = list(reader)
    rows[3]["y"] = "-0.59"
    rows[3]["event"] = "touchdown"
    rows[4]["x"] = "NA"
    rows[2]["team"] = "ball"
    rows[5]["team"] = "ball"
    _csv(tracking, columns, rows)
    report, replay = _qualify(path, _rehashed(path))
    assert replay["frames"][1]["events"] == ["touchdown"]
    assert replay["frames"][1]["players"] == []
    assert replay["frames"][1]["ball"] is not None
    quality = report["tracking"]["position_quality"]
    assert quality["omitted_total_position_rows"] == 2
    assert quality["omitted_missing_position_rows"] == 1
    assert quality["omitted_off_field_position_rows"] == 1
    assert quality["affected_source_frame_ids"] == [3]
    assert any("not clamped or interpolated" in w for w in report["warnings"])
    assert report["source_video_alignment_verified"] is False
