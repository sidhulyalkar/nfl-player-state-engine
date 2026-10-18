from __future__ import annotations

import csv
from pathlib import Path

import pytest

from player_state_engine.product.gameday_tracking import (
    import_bdb_2025_tracking,
    write_replay_json,
)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    fields = [
        "gameId", "playId", "nflId", "frameId", "x", "y",
        "club", "displayName", "jerseyNumber", "event", "playDirection",
        "s", "a", "o", "dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _rows() -> list[dict[str, str]]:
    base = {"gameId": "2024090800", "playId": "12", "playDirection": "right"}
    return [
        {**base, "nflId": "1", "frameId": "1", "x": "50", "y": "24", "club": "ABC", "jerseyNumber": "7", "event": "ball_snap"},
        {**base, "nflId": "2", "frameId": "1", "x": "54", "y": "24", "club": "XYZ"},
        {**base, "nflId": "", "frameId": "1", "x": "49", "y": "24"},
        {**base, "nflId": "1", "frameId": "3", "x": "50.5", "y": "24"},
        {**base, "nflId": "", "frameId": "3", "x": "50", "y": "24", "event": "pass_forward"},
        {**base, "gameId": "other", "frameId": "1", "nflId": "999", "x": "50", "y": "5"},
    ]


def _import(path: Path, **kwargs: object) -> dict:
    return import_bdb_2025_tracking(
        path, game_id="2024090800", play_id="12",
        license_acknowledged=True, license_identifier="user-confirmed-research-terms",
        **kwargs,
    )


def test_import_preserves_coordinates_and_missing_frames(tmp_path: Path) -> None:
    source = _write_csv(tmp_path / "tracking.csv", _rows())
    replay = _import(source, possession_team="ABC")
    assert replay["data_mode"] == "HISTORICAL_RESEARCH"
    assert replay["commercial_reuse_authorized"] is False
    assert replay["model_training_authorized"] is False
    assert replay["source_file_sha256"] and len(replay["source_file_sha256"]) == 64
    assert replay["frame_count"] == 2
    assert replay["missing_frame_count"] == 1
    assert replay["frame_coverage"] == pytest.approx(2 / 3)
    assert replay["frames"][0]["players"][0]["side"] == "offense"
    assert replay["frames"][0]["players"][1]["side"] == "defense"
    assert replay["frames"][0]["ball"]["is_ball"] is True
    assert replay["frames"][1]["t_seconds_nominal"] == pytest.approx(0.2)
    assert replay["frames"][1]["events"] == ["pass_forward"]
    assert replay["frames"][0]["players"][0]["z"] is None
    out = write_replay_json(replay, tmp_path / "replays" / "one.json")
    assert out.exists()
    assert '"RECORDED_FRAMES"' in out.read_text(encoding="utf-8")


def test_requires_rights_acknowledgement(tmp_path: Path) -> None:
    path = _write_csv(tmp_path / "tracking.csv", _rows())
    with pytest.raises(ValueError, match="source rights"):
        import_bdb_2025_tracking(path, game_id="2024090800", play_id="12")
    with pytest.raises(ValueError, match="source rights"):
        import_bdb_2025_tracking(
            path, game_id="2024090800", play_id="12",
            license_acknowledged=True, license_identifier="",
        )


@pytest.mark.parametrize("field,bad,match", [
    ("x", "121", "Out-of-bounds"),
    ("y", "55", "Out-of-bounds"),
    ("x", "NaN", "non-finite"),
    ("frameId", "0", "positive"),
    ("playDirection", "unknown", "Unknown playDirection"),
])
def test_invalid_source_fails_closed(
    tmp_path: Path, field: str, bad: str, match: str
) -> None:
    rows = _rows()
    rows[0][field] = bad
    path = _write_csv(tmp_path / "tracking.csv", rows)
    with pytest.raises(ValueError, match=match):
        _import(path)


def test_duplicate_entity_fails_closed(tmp_path: Path) -> None:
    rows = _rows()
    rows.insert(1, dict(rows[0]))
    path = _write_csv(tmp_path / "tracking.csv", rows)
    with pytest.raises(ValueError, match="Duplicate"):
        _import(path)


def test_no_match_does_not_invent_play(tmp_path: Path) -> None:
    path = _write_csv(tmp_path / "tracking.csv", _rows())
    with pytest.raises(ValueError, match="No tracking rows"):
        import_bdb_2025_tracking(
            path, game_id="2024090800", play_id="999",
            license_acknowledged=True, license_identifier="research",
        )


def test_row_safety_cap(tmp_path: Path) -> None:
    path = _write_csv(tmp_path / "tracking.csv", _rows())
    with pytest.raises(ValueError, match="safety limit"):
        _import(path, max_selected_rows=2)
