"""Synthetic multi-play export tests: never misrepresent fixtures as real NFL data."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from player_state_engine.product.bdb2019_batch_replay import (
    export_bdb2019_replay_batch,
    validate_play_ids,
)
from player_state_engine.product.bdb2019_source_qualification import (
    SOURCE_FILES,
    file_identifiers,
)
from player_state_engine.product.gameday_legacy_tracking import import_bdb_2019_example


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _source(tmp_path: Path) -> tuple[Path, dict[str, tuple[str, str, int]]]:
    root = tmp_path / "source"
    root.mkdir()
    _write_csv(root / "games.csv", [
        {"gameId": "2017090700", "homeTeamAbbr": "NE", "visitorTeamAbbr": "KC",
         "season": "2017", "week": "1"},
    ])
    _write_csv(root / "plays.csv", [
        {"gameId": "2017090700", "playId": "938", "possessionTeam": "KC",
         "quarter": "1", "down": "3", "yardsToGo": "7",
         "offenseFormation": "SHOTGUN", "personnel.offense": "1 RB, 2 TE, 2 WR"},
        {"gameId": "2017090700", "playId": "2756", "possessionTeam": "NE",
         "quarter": "3", "down": "NA", "yardsToGo": "NA",
         "offenseFormation": "NA", "personnel.offense": "NA"},
    ])
    rows = []
    for pid in ("938", "2756"):
        for frame in (1, 2):
            for nflid, team, x, y in (
                ("11", "away", "45", "20"),
                ("22", "home", "47", "23"),
                ("NA", "ball", "46", "21"),
            ):
                if pid == "2756" and frame == 2 and nflid == "11":
                    x = "NA"
                rows.append({
                    "gameId": "2017090700", "playId": pid,
                    "frame.id": str(frame), "nflId": nflid, "team": team,
                    "x": x, "y": y, "s": "2.2", "dir": "90",
                    "event": "ball_snap" if frame == 1 else "NA",
                    "displayName": "Test player", "jerseyNumber": "11",
                })
    _write_csv(root / SOURCE_FILES["tracking"][0], rows)
    return root, _hashes(root)


def _hashes(root: Path) -> dict[str, tuple[str, str, int]]:
    return {
        key: (filename, file_identifiers(root / filename)["git_blob_sha1"],
              (root / filename).stat().st_size)
        for key, (filename, _, _) in SOURCE_FILES.items()
    }


def _export(root: Path, out: Path, expected: dict, **kwargs: object) -> dict:
    return export_bdb2019_replay_batch(
        root, out, play_ids=["938", "2756"],
        license_acknowledged=True, license_identifier="local synthetic fixture",
        expectations=expected, **kwargs,
    )


def test_two_play_export_is_atomic_and_matches_existing_replay_adapter(tmp_path: Path) -> None:
    root, pins = _source(tmp_path)
    out = tmp_path / "private-session"
    result = _export(root, out, pins)
    assert result["qualification_status"] == "NONCANONICAL_FIXTURE_ONLY"
    assert result["source_video_alignment_verified"] is False
    assert result["play_count"] == 2
    assert sorted(p.name for p in out.iterdir()) == [
        "2017090700-2756-research-replay.json",
        "2017090700-938-research-replay.json", "manifest.json",
    ]
    assert (out / "manifest.json").is_file()
    for item in result["plays"]:
        replay = json.loads((out / item["file"]).read_text())
        metadata = replay["source_play_metadata"]
        assert metadata["provenance"] == "NONCANONICAL_TEST_FIXTURE"
        assert replay["source_file_sha256"] == result["source_file_sha256"]
        assert replay["possession_team"] == metadata["possession_team"]
        expected_side = "away" if item["play_id"] == "938" else "home"
        assert metadata["offense_side"] == expected_side
        original = import_bdb_2019_example(
            root / SOURCE_FILES["tracking"][0],
            game_id="2017090700", play_id=item["play_id"],
            license_acknowledged=True, license_identifier="local synthetic fixture",
            offense_side=expected_side,
            position_policy="omit_off_field_with_audit",
        )
        assert replay["frames"] == original["frames"]
        assert replay["position_quality"] == original["position_quality"]
        assert replay["rows"] == original["rows"]
        assert replay["source_file_sha256"] == original["source_file_sha256"]
    a = json.loads((out / "2017090700-938-research-replay.json").read_text())
    b = json.loads((out / "2017090700-2756-research-replay.json").read_text())
    assert a["source_play_metadata"]["offense_formation_charted"] == "SHOTGUN"
    assert a["source_play_metadata"]["down"] == 3
    assert a["frames"][0]["players"][0]["side"] == "offense"
    assert b["source_play_metadata"]["offense_formation_charted"] is None
    assert b["source_play_metadata"]["down"] is None
    assert b["frames"][0]["players"][0]["side"] == "defense"
    assert b["position_quality"]["omitted_missing_position_rows"] == 1


def test_duplicate_or_malicious_play_ids_fail_before_any_io() -> None:
    for ids in ([], ["938", "938"], ["../secret"], ["-5"], ["１２３"], ["0" * 11],
                [str(i) for i in range(13)]):
        with pytest.raises(ValueError):
            validate_play_ids(ids)
    assert validate_play_ids(["938", "2756"]) == ["938", "2756"]


def test_bad_source_identity_rejected_without_writing_any_replay(tmp_path: Path) -> None:
    root, pins = _source(tmp_path)
    with (root / "games.csv").open("a", encoding="utf-8") as f:
        f.write("unexpected extra row\n")
    out = tmp_path / "session"
    with pytest.raises(ValueError, match="pinned official Git blob"):
        _export(root, out, pins)
    assert not out.exists()


def test_bad_second_play_rolls_back_entire_batch(tmp_path: Path) -> None:
    root, _ = _source(tmp_path)
    plays = root / "plays.csv"
    plays.write_text(plays.read_text().replace(",NE,3,NA,", ",CHI,3,NA,"))
    out = tmp_path / "batch"
    with pytest.raises(ValueError, match="Possession team cannot be reconciled"):
        _export(root, out, _hashes(root))
    assert not out.exists()
    assert not any(p.name.startswith(".pse-playlab-staging-") for p in tmp_path.iterdir())


def test_invalid_tracked_team_in_second_play_rolls_back_first(tmp_path: Path) -> None:
    root, _ = _source(tmp_path)
    path = root / SOURCE_FILES["tracking"][0]
    content = path.read_text()
    path.write_text(content.replace("2756,1,11,away", "2756,1,11,ball"))
    out = tmp_path / "batch"
    with pytest.raises(ValueError, match="Player must identify"):
        _export(root, out, _hashes(root))
    assert not out.exists()


def test_output_cannot_overwrite_prior_session(tmp_path: Path) -> None:
    root, pins = _source(tmp_path)
    dest = tmp_path / "private"
    dest.mkdir()
    marker = dest / "keep.txt"
    marker.write_text("do not overwrite")
    with pytest.raises(ValueError, match="new output directory"):
        _export(root, dest, pins)
    assert marker.read_text() == "do not overwrite"


def test_official_label_never_applied_to_noncanonical_source(tmp_path: Path) -> None:
    root, _ = _source(tmp_path)
    with pytest.raises(ValueError, match="pinned official Git blob"):
        export_bdb2019_replay_batch(
            root, tmp_path / "private", play_ids=["938"],
            license_acknowledged=True, license_identifier="fixture",
        )


def test_requires_source_terms_and_all_metadata(tmp_path: Path) -> None:
    root, pins = _source(tmp_path)
    with pytest.raises(ValueError, match="Review source rights"):
        export_bdb2019_replay_batch(
            root, tmp_path / "batch", play_ids=["938"], expectations=pins,
        )
    (root / "plays.csv").unlink()
    with pytest.raises(ValueError, match="Missing plays source CSV"):
        _export(root, tmp_path / "batch", pins)


@pytest.mark.parametrize(("old", "new", "message"), [
    (",1,3,7,", ",0,3,7,", "Out-of-range source quarter"),
    (",1,3,7,", ",7,3,7,", "Out-of-range source quarter"),
    (",1,3,7,", ",1,0,7,", "Out-of-range source down"),
    (",1,3,7,", ",1,5,7,", "Out-of-range source down"),
    (",1,3,7,", ",1,3,100,", "Out-of-range source yards to go"),
])
def test_invalid_source_charting_rolls_back_batch(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    root, _ = _source(tmp_path)
    plays = root / "plays.csv"
    original = plays.read_text()
    assert old in original
    plays.write_text(original.replace(old, new, 1))
    out = tmp_path / "bad-charting"
    with pytest.raises(ValueError, match=message):
        _export(root, out, _hashes(root))
    assert not out.exists()


def test_oversized_source_charted_label_rejects_entire_batch(tmp_path: Path) -> None:
    root, _ = _source(tmp_path)
    plays = root / "plays.csv"
    original = plays.read_text()
    assert "SHOTGUN" in original
    plays.write_text(original.replace("SHOTGUN", "X" * 91, 1))
    out = tmp_path / "bad-label"
    with pytest.raises(ValueError, match="Source charted label exceeds 90 characters"):
        _export(root, out, _hashes(root))
    assert not out.exists()
