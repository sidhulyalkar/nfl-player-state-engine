"""AngleIQ private source ingestion: no network, no footage redistribution."""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.build_angleiq_manifest import assemble_manifest, _digest, _read_config


def _config() -> dict:
    return {
        "schema_version": 1,
        "game_id": "2017090700",
        "play_id": "938",
        "rights": {
            "declaration": "Synthetic local unit-test source, not real NFL media",
            "local_playback_authorized": True,
            "derivative_analysis_authorized": True,
            "redistribution_authorized": False,
        },
        "events": [
            {
                "id": "foot",
                "kind": "boundary_catch",
                "event_time_s": 1.1,
                "label": "Ground contact",
                "question": "Was a receiver in bounds?",
            },
        ],
        "angles": [{
            "id": "sideline",
            "name": "Research sideline",
            "kind": "sideline",
            "source": {"type": "local_file", "filename": "test.mp4"},
            "anchors": [{"event_time_s": 0, "media_time_s": .2},
                        {"event_time_s": 2, "media_time_s": 2.2}],
            "evidence": [{
                "event_id": "foot",
                "provenance": "human_reviewed",
                "ball": 1.0, "boundary": 1.0, "control": None,
                "ground_contact": .9, "field_context": .2,
                "clarity": .9, "continuity": .8, "occlusion": .1,
                "note": "Synthetic observation only",
            }],
        }],
    }


def test_local_video_metadata_and_streamed_digest(tmp_path: Path) -> None:
    media = tmp_path / "test.mp4"
    raw = b"synthetic footage bytes only"
    media.write_bytes(raw)
    with patch("scripts.build_angleiq_manifest._duration", return_value=3.1):
        manifest = assemble_manifest(_config(), tmp_path)
    angle = manifest["angles"][0]
    assert manifest["data_mode"] == "RIGHTS_DECLARED_VIDEO_RESEARCH"
    assert angle["source"]["filename"] == media.name
    assert angle["source"]["bytes"] == len(raw)
    assert angle["source"]["duration_s"] == 3.1
    assert angle["source"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert _digest(media) == angle["source"]["sha256"]
    assert angle["evidence"][0]["provenance"] == "human_reviewed"
    assert manifest["rights"]["redistribution_authorized"] is False


@pytest.mark.parametrize("mutate,message", [
    (lambda c: c["rights"].update(redistribution_authorized=True), "rights"),
    (lambda c: c["rights"].update(local_playback_authorized=False), "rights"),
    (lambda c: c["angles"][0]["source"].update(filename="../other.mp4"), "filename"),
    (lambda c: c["angles"][0]["anchors"].append(
        {"event_time_s": 1.0, "media_time_s": 1.3}), "anchors"),
    (lambda c: c["angles"][0]["evidence"][0].update(boundary=7), "Visibility"),
    (lambda c: c["angles"][0].update(id=""), "camera"),
    (lambda c: c["events"][0].update(event_time_s=-1), "question"),
])
def test_reject_malformed_rights_or_labels(tmp_path: Path, mutate, message: str) -> None:
    (tmp_path / "test.mp4").write_bytes(b"source")
    config = _config()
    mutate(config)
    with patch("scripts.build_angleiq_manifest._duration", return_value=3.1):
        with pytest.raises(ValueError, match=message):
            assemble_manifest(config, tmp_path)


def test_symlink_media_refused_even_when_its_bytes_match(tmp_path: Path) -> None:
    actual = tmp_path / "original.mp4"
    actual.write_bytes(b"source")
    (tmp_path / "test.mp4").symlink_to(actual)
    with patch("scripts.build_angleiq_manifest._duration", return_value=3.1):
        with pytest.raises(ValueError, match="regular non-symlinked"):
            assemble_manifest(_config(), tmp_path)


def test_source_video_duration_not_invented_when_probe_fails(tmp_path: Path) -> None:
    (tmp_path / "test.mp4").write_bytes(b"source")
    with patch("scripts.build_angleiq_manifest._duration", side_effect=ValueError("probe unavailable")):
        with pytest.raises(ValueError, match="probe unavailable"):
            assemble_manifest(_config(), tmp_path)


def test_reject_local_video_over_limit_before_any_probe(tmp_path: Path) -> None:
    name = tmp_path / "test.mp4"
    with name.open("wb") as output:
        output.truncate(40_000_001)
    with patch("scripts.build_angleiq_manifest._duration") as probe:
        with pytest.raises(ValueError, match="per-file size"):
            assemble_manifest(_config(), tmp_path)
        probe.assert_not_called()


def test_external_viewer_metadata_does_not_read_local_media(tmp_path: Path) -> None:
    config = _config()
    config["rights"]["local_playback_authorized"] = False
    config["rights"]["derivative_analysis_authorized"] = False
    config["angles"][0]["source"] = {
        "type": "external_link", "url": "https://www.nfl.com/videos/example"
    }
    config["angles"][0]["anchors"] = []
    result = assemble_manifest(config, tmp_path)
    assert result["angles"][0]["source"]["type"] == "external_link"
    assert result["angles"][0]["evidence"][0]["note"] == "Synthetic observation only"


def test_config_must_be_real_file(tmp_path: Path) -> None:
    source = tmp_path / "config.json"
    source.write_text('{"schema_version":1}', encoding="utf-8")
    assert _read_config(source) == {"schema_version": 1}
    alias = tmp_path / "alias.json"
    alias.symlink_to(source)
    with pytest.raises(ValueError, match="non-symlinked"):
        _read_config(alias)
