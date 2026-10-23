from __future__ import annotations

import csv
from pathlib import Path

import pytest

from player_state_engine.product.gameday_legacy_tracking import import_bdb_2019_example


def _write(path: Path, rows: list[dict[str, str]]) -> Path:
    columns = [
        "gameId", "playId", "nflId", "frame.id", "x", "y", "team",
        "displayName", "jerseyNumber", "event", "s", "o", "dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _rows() -> list[dict[str, str]]:
    p = {"gameId": "2017090700", "playId": "2756"}
    return [
        {**p, "nflId": "11", "frame.id": "1", "x": "44.1", "y": "22",
         "team": "away", "displayName": "Receiver Example", "event": "ball_snap", "s": "1.5"},
        {**p, "nflId": "25", "frame.id": "1", "x": "47", "y": "22.5",
         "team": "home", "displayName": "Defender Example"},
        {**p, "nflId": "NA", "frame.id": "1", "x": "44", "y": "22",
         "team": "football"},
        {**p, "nflId": "11", "frame.id": "3", "x": "47", "y": "22",
         "team": "away", "event": "pass_arrived"},
        {**p, "nflId": "25", "frame.id": "3", "x": "48", "y": "21",
         "team": "home"},
        {**p, "gameId": "2017091004", "nflId": "99", "frame.id": "1",
         "x": "49", "y": "20", "team": "home"},
    ]


def _convert(path: Path, **opts: object) -> dict:
    return import_bdb_2019_example(
        path,
        game_id="2017090700",
        play_id="2756",
        license_acknowledged=True,
        license_identifier="reviewed-original-bdb-repository-rules",
        **opts,
    )


def test_original_bdb_normalizes_recorded_frames_and_side(tmp_path: Path) -> None:
    replay = _convert(_write(tmp_path / "sample.csv", _rows()), offense_side="away")
    assert replay["data_mode"] == "HISTORICAL_RESEARCH"
    assert replay["tracking_fidelity"] == "RECORDED_FRAMES"
    assert replay["commercial_reuse_authorized"] is False
    assert replay["frame_count"] == 2
    assert replay["missing_frame_count"] == 1
    assert replay["frame_coverage"] == pytest.approx(2 / 3)
    assert replay["frames"][0]["players"][0]["side"] == "offense"
    assert replay["frames"][0]["players"][1]["side"] == "defense"
    assert replay["frames"][0]["ball"]["nfl_id"] is None
    assert replay["frames"][0]["events"] == ["ball_snap"]
    assert replay["frames"][1]["t_seconds_nominal"] == pytest.approx(.2)
    assert len(replay["source_file_sha256"]) == 64
    assert replay["play_direction"] is None


def test_original_bdb_does_not_infer_possession(tmp_path: Path) -> None:
    replay = _convert(_write(tmp_path / "sample.csv", _rows()))
    assert replay["offense_side"] is None
    assert replay["frames"][0]["players"][0]["side"] is None
    assert replay["frames"][0]["players"][1]["side"] is None


@pytest.mark.parametrize(("field", "value", "match"), [
    ("x", "122", "Out-of-bounds"),
    ("x", "nan", "Out-of-bounds"),
    ("x", "inf", "non-finite"),
    ("team", "CHI", "Invalid home/away"),
    ("frame.id", "0", "positive"),
])
def test_invalid_original_tracking_fails_closed(
    tmp_path: Path, field: str, value: str, match: str
) -> None:
    data = _rows()
    data[0][field] = value
    with pytest.raises(ValueError, match=match):
        _convert(_write(tmp_path / "sample.csv", data))


def test_original_tracking_duplicate_identity_fails_closed(tmp_path: Path) -> None:
    data = _rows()
    data.insert(1, dict(data[0]))
    with pytest.raises(ValueError, match="Duplicate identity"):
        _convert(_write(tmp_path / "sample.csv", data))


def test_original_tracking_requires_rights_acknowledgement(tmp_path: Path) -> None:
    data = _write(tmp_path / "sample.csv", _rows())
    with pytest.raises(ValueError, match="source rights"):
        import_bdb_2019_example(data, game_id="2017090700", play_id="2756")


def test_original_tracking_missing_play_fails_closed(tmp_path: Path) -> None:
    path = _write(tmp_path / "sample.csv", _rows())
    with pytest.raises(ValueError, match="No tracking rows"):
        import_bdb_2019_example(
            path, game_id="2017090700", play_id="9999",
            license_acknowledged=True, license_identifier="reviewed",
        )

def test_original_tracking_missing_optional_numbers_are_not_invented(tmp_path: Path) -> None:
    data = _rows()
    data[0]["s"] = "NA"
    data[0]["o"] = "NA"
    replay = _convert(_write(tmp_path / "sample.csv", data))
    entity = replay["frames"][0]["players"][0]
    assert entity["speed_yards_per_s"] is None
    assert entity["orientation_deg"] is None


def test_official_nfl_ball_team_label_normalizes_as_ball(tmp_path: Path) -> None:
    data = _rows()
    data[2]["team"] = "ball"
    replay = _convert(_write(tmp_path / "official_ball.csv", data), offense_side="away")
    ball = replay["frames"][0]["ball"]
    assert ball is not None
    assert ball["nfl_id"] is None
    assert ball["is_ball"] is True
    assert ball["team"] == "ball"
    assert replay["position_quality"]["omitted_total_position_rows"] == 0


def test_real_world_post_touchdown_outside_sideline_is_explicitly_omitted(
    tmp_path: Path,
) -> None:
    data = _rows()
    data[3]["y"] = "-0.59"
    data[3]["event"] = "touchdown"
    data[4]["x"] = "NA"
    path = _write(tmp_path / "off_sideline.csv", data)
    with pytest.raises(ValueError, match="Out-of-bounds"):
        _convert(path)
    replay = _convert(path, position_policy="omit_off_field_with_audit")
    assert replay["rows"] == 5
    assert replay["frame_count"] == 2
    assert replay["missing_frame_count"] == 1
    assert replay["frames"][1]["events"] == ["touchdown"]
    assert replay["frames"][1]["players"] == []
    q = replay["position_quality"]
    assert q["omitted_total_position_rows"] == 2
    assert q["omitted_off_field_position_rows"] == 1
    assert q["omitted_missing_position_rows"] == 1
    assert q["affected_source_frame_ids"] == [3]
    assert q["never_clamped_or_interpolated"] is True


def test_unknown_position_policy_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="policy"):
        _convert(
            _write(tmp_path / "badpolicy.csv", _rows()),
            position_policy="clamp_outside_coords",
        )


def test_audited_missing_coordinate_cannot_hide_invalid_player_team(
    tmp_path: Path,
) -> None:
    data = _rows()
    data[0]["x"] = "NA"
    data[0]["team"] = "ball"
    with pytest.raises(ValueError, match="Player must identify home or away"):
        _convert(
            _write(tmp_path / "bad_hidden_player.csv", data),
            position_policy="omit_off_field_with_audit",
        )


def test_audited_missing_coordinate_cannot_hide_bad_ball_label(
    tmp_path: Path,
) -> None:
    data = _rows()
    data[2]["x"] = "NA"
    data[2]["team"] = "away"
    with pytest.raises(ValueError, match="Ball row must not carry"):
        _convert(
            _write(tmp_path / "bad_hidden_ball.csv", data),
            position_policy="omit_off_field_with_audit",
        )
