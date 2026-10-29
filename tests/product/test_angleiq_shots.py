"""Bounded FFmpeg scene extraction only, no actual NFL video in tests."""
from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from scripts.detect_angleiq_shots import analyze_local_video, scene_candidates, shot_intervals


def test_scene_timestamps_are_deduplicated_and_short_fragments_removed() -> None:
    log = (
        "[Parsed_showinfo_3] n:0 pts_time:0.05 pos:22\n"
        "[Parsed_showinfo_3] n:1 pts_time:0.55 pos:88\n"
        "[Parsed_showinfo_3] n:2 pts_time:0.56 pos:90\n"
        "[Parsed_showinfo_3] n:3 pts_time:2.10 pos:110\n"
        "[Parsed_showinfo_3] n:4 pts_time:2.88 pos:112\n"
    )
    assert scene_candidates(log, 3) == [.55, 2.1, 2.88] if False else [.55, 2.1]
    shots = shot_intervals([.55, 2.1], 3)
    assert len(shots) == 3
    assert shots[0]["start_video_s"] == 0
    assert shots[-1]["end_video_s"] == 3
    assert all(s["qualification"] == "SCENE_BOUNDARY_CANDIDATE_ONLY" for s in shots)


def test_local_only_scanner_emits_source_boundaries_not_highlight_judgments(tmp_path: Path) -> None:
    file = tmp_path / "angle.webm"
    file.write_bytes(b"synthetic local camera bytes")
    fake = CompletedProcess(args=["ffmpeg"], returncode=0,
                            stdout="", stderr="n:0 pts_time:1.0\nn:1 pts_time:3.0")
    with patch("scripts.detect_angleiq_shots._duration", return_value=5.0), \
         patch("scripts.detect_angleiq_shots.subprocess.run", return_value=fake) as ffmpeg:
        result = analyze_local_video(file, max_seconds=4)
    assert result["data_mode"] == "LOCAL_VIDEO_SCENE_CANDIDATES"
    assert result["candidate_cut_count"] == 2
    assert len(result["shots"]) == 3
    assert result["entire_source_scanned"] is False
    assert result["authority"] == "RESEARCH_SCENE_CANDIDATES_ONLY"
    command = ffmpeg.call_args.args[0]
    assert "-protocol_whitelist" in command
    assert "file,pipe" in command
    assert "http" not in " ".join(command)


@pytest.mark.parametrize("kwargs,error", [
    ({"max_seconds":0}, "window"),
    ({"frame_sampling_fps":0}, "frames"),
    ({"scene_threshold":.9}, "threshold"),
])
def test_invalid_scan_settings_fail_before_decoder(tmp_path: Path, kwargs, error: str) -> None:
    file = tmp_path / "angle.webm"
    file.write_bytes(b"synthetic")
    with patch("scripts.detect_angleiq_shots.subprocess.run") as ffmpeg:
        with pytest.raises(ValueError, match=error):
            analyze_local_video(file, **kwargs)
        ffmpeg.assert_not_called()


def test_symlink_and_oversized_video_rejected_before_ffmpeg(tmp_path: Path) -> None:
    actual = tmp_path / "recorded.webm"
    actual.write_bytes(b"source")
    alias = tmp_path / "alias.webm"
    alias.symlink_to(actual)
    with pytest.raises(ValueError, match="regular video"):
        analyze_local_video(alias)
    with actual.open("wb") as out:
        out.truncate(40_000_001)
    with pytest.raises(ValueError, match="regular video"):
        analyze_local_video(actual)
