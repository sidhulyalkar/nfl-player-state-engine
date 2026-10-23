"""Fail-closed game timeline source-join and negative controls."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from player_state_engine.product.bdb2019_game_timeline import (
    build_bdb2019_game_timeline,
    write_game_timeline,
)
from player_state_engine.product.bdb2019_source_qualification import (
    file_identifiers,
)


def _csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def sources(tmp_path: Path) -> tuple[Path, Path, dict]:
    root = tmp_path / "sources"
    root.mkdir()
    _csv(root / "tracking.csv", ["gameId", "playId"], [
        {"gameId": "2017090700", "playId": "12"},
        {"gameId": "2017090700", "playId": "4"},
    ])
    _csv(root / "games.csv",
         ["gameId", "homeTeamAbbr", "visitorTeamAbbr", "season", "week"], [{
             "gameId": "2017090700", "homeTeamAbbr": "NE",
             "visitorTeamAbbr": "KC", "season": "2017", "week": "1",
         }])
    play_rows = [
        {
            "gameId": "2017090700", "playId": pid, "quarter": quarter,
            "down": down, "yardsToGo": "8", "possessionTeam": possession,
            "gameClock": "09:28", "playDescription": "A charted source description.",
            "offenseFormation": "SHOTGUN", "personnel.offense": "1 RB, 3 WR, 1 TE",
        }
        for pid, quarter, down, possession in [
            ("12", "2", "3", "KC"), ("4", "1", "1", "NE")
        ]
    ]
    _csv(root / "plays.csv", list(play_rows[0]), play_rows)
    expectations = {
        key: (path, file_identifiers(root / path)["git_blob_sha1"],
              file_identifiers(root / path)["bytes"])
        for key, path in {
            "tracking": "tracking.csv", "plays": "plays.csv", "games": "games.csv"
        }.items()
    }
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({
        "data_mode": "HISTORICAL_RESEARCH_METADATA_ONLY",
        "positions_included": False, "source_video_alignment_verified": False,
        "game_id": "2017090700", "source_sha256": file_identifiers(
            root / "tracking.csv"
        )["sha256"],
        "play_count": 2,
        "plays": [
            {"game_id": "2017090700", "play_id": pid, "source_rows": rows}
            for pid, rows in [("4", 10), ("12", 19)]
        ],
    }))
    return root, catalog, expectations


def _build(
    sources: tuple[Path, Path, dict], **kwargs
) -> dict:
    source, catalog, expectations = sources
    return build_bdb2019_game_timeline(
        source, catalog, expectations=expectations,
        license_acknowledged=True, license_identifier="test-only", **kwargs
    )


def test_joins_exact_verified_source_metadata_without_synthetic_drives(
    sources: tuple[Path, Path, dict], tmp_path: Path
) -> None:
    result = _build(sources)
    assert result["qualification_status"] == "SYNTHETIC_OR_NONCANONICAL_FIXTURE_ONLY"
    assert result["positions_included"] is False
    assert result["drive_boundaries_verified"] is False
    assert result["model_training_authorized"] is False
    assert result["source_video_alignment_verified"] is False
    assert result["play_count"] == 2
    assert [r["play_id"] for r in result["plays"]] == ["4", "12"]
    assert [r["possession_team"] for r in result["plays"]] == ["NE", "KC"]
    assert [r["offense_side"] for r in result["plays"]] == ["home", "away"]
    assert result["plays"][1]["quarter"] == 2
    assert result["plays"][1]["description_charted"] == "A charted source description."
    assert all("players" not in row and "frames" not in row for row in result["plays"])
    output = write_game_timeline(result, tmp_path / "timeline.json")
    assert json.loads(output.read_text()) == result


def test_requires_terms_consent(sources: tuple[Path, Path, dict]) -> None:
    root, catalog, expectations = sources
    with pytest.raises(ValueError, match="acknowledgement"):
        build_bdb2019_game_timeline(
            root, catalog, expectations=expectations,
            license_acknowledged=False, license_identifier="test-only"
        )


def test_different_source_tracking_sha_refused(sources: tuple[Path, Path, dict]) -> None:
    root, catalog, _ = sources
    value = json.loads(catalog.read_text())
    value["source_sha256"] = "0" * 64
    catalog.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="provenance"):
        _build(sources)


def test_mutated_source_csv_refused(sources: tuple[Path, Path, dict]) -> None:
    root, _, _ = sources
    with (root / "plays.csv").open("a") as stream:
        stream.write("malicious changed bytes\n")
    with pytest.raises(ValueError, match="pinned official Git blob"):
        _build(sources)


def test_missing_matching_play_refused(sources: tuple[Path, Path, dict]) -> None:
    root, _, expectations = sources
    _csv(root / "plays.csv", [
        "gameId", "playId", "quarter", "down", "yardsToGo", "possessionTeam"
    ], [{
        "gameId": "2017090700", "playId": "4", "quarter": "1",
        "down": "1", "yardsToGo": "8", "possessionTeam": "NE",
    }])
    meta = file_identifiers(root / "plays.csv")
    expectations["plays"] = ("plays.csv", meta["git_blob_sha1"], meta["bytes"])
    with pytest.raises(ValueError, match="unmatched"):
        _build(sources)


def test_possession_not_reconciled_is_refused(sources: tuple[Path, Path, dict]) -> None:
    root, _, expectations = sources
    contents = (root / "plays.csv").read_text().replace(",KC,", ",DAL,")
    (root / "plays.csv").write_text(contents)
    meta = file_identifiers(root / "plays.csv")
    expectations["plays"] = ("plays.csv", meta["git_blob_sha1"], meta["bytes"])
    with pytest.raises(ValueError, match="possession"):
        _build(sources)


def test_tracking_coordinates_in_catalog_refused(
    sources: tuple[Path, Path, dict]
) -> None:
    _, catalog, _ = sources
    value = json.loads(catalog.read_text())
    value["plays"][0]["frames"] = [{"x": 20, "y": 35}]
    catalog.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="tracking positions"):
        _build(sources)
