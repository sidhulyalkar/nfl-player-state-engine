#!/usr/bin/env python3
"""Detect candidate shot boundaries in an authorized local football video.

No scraping, network fetching, source duplication, player identification, or
claim about best highlight angles. FFmpeg scene-change candidates are not
evidence of a play event or a camera type.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
from pathlib import Path

from scripts.build_angleiq_manifest import MAX_CLIP_BYTES, _digest, _duration

SCENE_TIME = re.compile(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)")


def scene_candidates(
    diagnostics: str, seconds: float, *, minimum_duration: float = 0.35,
) -> list[float]:
    """Normalize FFmpeg showinfo timestamps without inventing missing cuts."""
    if not (0 < seconds <= 3600 and .1 <= minimum_duration <= 5):
        raise ValueError("Invalid shot-analysis window or minimum shot duration")
    found: list[float] = []
    previous = 0.0
    for m in SCENE_TIME.finditer(diagnostics):
        t = float(m.group(1))
        if t <= previous or t >= seconds:
            continue
        if t - previous < minimum_duration or seconds - t < minimum_duration:
            continue
        if len(found) >= 500:
            raise ValueError("Too many candidate cuts; review source or threshold")
        found.append(round(t, 3))
        previous = t
    return found


def shot_intervals(cuts: list[float], seconds: float) -> list[dict]:
    """Segments are descriptive candidates, not validated event highlights."""
    boundaries = [0.0, *cuts, round(seconds, 3)]
    return [
        {"start_video_s":a, "end_video_s":b,
         "duration_s":round(b - a, 3), "qualification":"SCENE_BOUNDARY_CANDIDATE_ONLY"}
        for a, b in zip(boundaries, boundaries[1:])
        if b > a
    ]


def analyze_local_video(
    path: Path, *, max_seconds: float = 45.0,
    frame_sampling_fps: int = 8, scene_threshold: float = 0.32,
) -> dict:
    if not (.05 <= scene_threshold <= .8):
        raise ValueError("Scene threshold must be in [0.05, 0.8]")
    if not (1 <= frame_sampling_fps <= 12):
        raise ValueError("Sampled scene detection must use 1-12 frames/s")
    if not (1 <= max_seconds <= 120):
        raise ValueError("Analysis window must be between 1 and 120 seconds")
    if path.suffix.lower() not in {".mp4", ".webm"}:
        raise ValueError("Only local MP4/WebM camera files supported")
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise ValueError("Camera source does not exist") from exc
    if not stat.S_ISREG(file_stat.st_mode) or not 0 < file_stat.st_size <= MAX_CLIP_BYTES:
        raise ValueError("Camera source must be a regular video file <= 40 MB")
    duration = _duration(path)
    window = round(min(duration, max_seconds), 3)
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-hide_banner", "-v", "info",
                "-protocol_whitelist", "file,pipe",
                "-i", str(path), "-t", str(window), "-an", "-sn",
                "-vf", f"fps={frame_sampling_fps},scale=480:-1,"
                f"select='gt(scene,{scene_threshold})',showinfo",
                "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=90, check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError) as exc:
        raise ValueError("Offline FFmpeg scene scan failed or exceeded 90 seconds") from exc
    cuts = scene_candidates(result.stderr, window)
    return {
        "schema_version": 1,
        "data_mode": "LOCAL_VIDEO_SCENE_CANDIDATES",
        "source_filename": path.name,
        "source_sha256": _digest(path),
        "source_bytes": file_stat.st_size,
        "source_duration_s": duration,
        "analyzed_duration_s": window,
        "entire_source_scanned": window >= duration - .001,
        "method": {
            "name": "ffmpeg_sampled_scene_threshold",
            "sample_fps": frame_sampling_fps,
            "scene_threshold": scene_threshold,
            "scene_time_basis": "video_pts_seconds",
        },
        "candidate_cut_count": len(cuts),
        "shots": shot_intervals(cuts, window),
        "authority": "RESEARCH_SCENE_CANDIDATES_ONLY",
        "note": "Not a camera label, highlight rating, human review, or game event synchronization.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-seconds", type=float, default=45.0)
    parser.add_argument("--fps", type=int, default=8)
    parser.add_argument("--threshold", type=float, default=.32)
    parser.add_argument("--acknowledge-source-terms", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_source_terms:
        parser.error("Review rights to process this local video before scanning.")
    report = analyze_local_video(
        args.video, max_seconds=args.max_seconds, frame_sampling_fps=args.fps,
        scene_threshold=args.threshold,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        args.output.unlink(missing_ok=True)
        raise
    print(f"Found {report['candidate_cut_count']} candidate shot boundary/boundaries.")
    print("Research metadata only. No video frames exported or source footage redistributed.")


if __name__ == "__main__":
    main()
