#!/usr/bin/env python3
"""Create a private, rights-declared AngleIQ manifest from authorized local video.

This tool does not find, download, scrape, copy, transcode or upload NFL footage.
Source camera annotations and video-event anchors are declared, not inferred.

Usage:
 python scripts/build_angleiq_manifest.py --config /private/angleiq-config.json \
   --media-dir /private/authorized-angles --output /private/play-angleiq.json \
   --acknowledge-source-terms
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

MAX_CLIP_BYTES = 40_000_000
MAX_SELECTION_BYTES = 160_000_000
MAX_CONFIG_BYTES = 250_000
MEDIA_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,127}\.(mp4|webm)$", re.I)
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
ANGLE_KINDS = {"broadcast", "sideline", "end_zone", "goal_line", "other"}
EVENT_KINDS = {"boundary_catch", "goal_line", "possession", "route_context", "general"}
DIMENSIONS = (
    "ball", "boundary", "control", "ground_contact", "field_context",
    "clarity", "continuity", "occlusion",
)


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _finite_number(value: object, minimum: float = 0, maximum: float = 3600) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and minimum <= float(value) <= maximum
        and float("-inf") < float(value) < float("inf")
    )


def _read_config(config_path: Path) -> dict:
    _require(config_path.is_file() and not config_path.is_symlink(),
             "Config must be a regular, non-symlinked local JSON file")
    _require(config_path.stat().st_size <= MAX_CONFIG_BYTES,
             "Config too large")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    _require(isinstance(data, dict), "Expected config JSON object")
    return data


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as file:
        for part in iter(lambda: file.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def _duration(path: Path) -> float:
    """Read source duration; do not invent a nominal duration on probe errors."""
    try:
        command = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=15, check=True,
        )
        seconds = float(json.loads(command.stdout)["format"]["duration"])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            ValueError, TypeError, KeyError, json.JSONDecodeError, FileNotFoundError) as error:
        raise ValueError(f"Could not probe video duration: {path.name}") from error
    _require(_finite_number(seconds, 0.000001, 3600),
             "Video duration must be positive and <= 3600 s")
    return seconds


def _check_anchors(anchors: object, duration: float | None) -> None:
    _require(isinstance(anchors, list) and len(anchors) <= 16,
             "Each camera must have <= 16 explicit alignment anchors")
    previous = None
    for point in anchors:
        _require(isinstance(point, dict), "Invalid angle anchor")
        t = point.get("event_time_s")
        v = point.get("media_time_s")
        _require(_finite_number(t, 0, 300) and _finite_number(v) and
                 (duration is None or v <= duration), "Invalid source anchor")
        if previous is not None:
            a, b = previous
            _require(t > a and v > b and abs((t - a) - (v - b)) <= .2,
                     "Unordered anchors or >200 ms timing drift; slow-motion not qualified")
        previous = (t, v)


def _check_evidence(evidence: object, events: set[str]) -> None:
    _require(isinstance(evidence, list) and len(evidence) <= len(events),
             "Invalid angle evidence annotations")
    seen = set()
    for row in evidence:
        _require(isinstance(row, dict) and row.get("event_id") in events and
                 row["event_id"] not in seen and
                 row.get("provenance") in {"human_reviewed", "unvalidated_model"},
                 "Unknown or duplicated event annotation")
        seen.add(row["event_id"])
        _require(all(row.get(d) is None or _finite_number(row.get(d), 0, 1)
                     for d in DIMENSIONS), "Visibility values must be in [0,1] or null")
        _require(row.get("note") is None or (
            isinstance(row["note"], str) and 0 < len(row["note"]) <= 360
        ), "Invalid annotation note")


def assemble_manifest(config: dict, media_dir: Path) -> dict:
    """Pure input/metadata boundary aside from checking pinned local video bytes."""
    _require(config.get("schema_version") == 1, "Config requires schema_version 1")
    game_id = config.get("game_id")
    play_id = config.get("play_id")
    _require(isinstance(game_id, str) and re.fullmatch(r"\d{10}", game_id) is not None,
             "Invalid game ID")
    _require(isinstance(play_id, str) and re.fullmatch(r"\d{1,10}", play_id) is not None,
             "Invalid play ID")
    rights = config.get("rights")
    _require(isinstance(rights, dict) and
             isinstance(rights.get("declaration"), str) and
             0 < len(rights["declaration"].strip()) <= 250 and
             isinstance(rights.get("local_playback_authorized"), bool) and
             isinstance(rights.get("derivative_analysis_authorized"), bool) and
             rights.get("redistribution_authorized") is False,
             "Explicit restrictive source rights declaration required")
    events = config.get("events")
    _require(isinstance(events, list) and 1 <= len(events) <= 24,
             "1-24 event questions required")
    event_ids = set()
    for e in events:
        _require(isinstance(e, dict) and
                 isinstance(e.get("id"), str) and ID_PATTERN.fullmatch(e["id"]) is not None and
                 e["id"] not in event_ids and
                 e.get("kind") in EVENT_KINDS and
                 _finite_number(e.get("event_time_s"), 0, 300) and
                 all(isinstance(e.get(k), str) and 0 < len(e[k]) <= mx
                     for k, mx in (("label", 100), ("question", 240))),
                 "Invalid or duplicate research question")
        event_ids.add(e["id"])
    angles = config.get("angles")
    _require(isinstance(angles, list) and 1 <= len(angles) <= 8,
             "1-8 camera angles required")
    _require(media_dir.is_dir() and not media_dir.is_symlink(),
             "Media root must be a real, non-symlink directory")
    seen_angles: set[str] = set()
    seen_files: set[str] = set()
    total_bytes = 0
    enriched = []
    for angle in angles:
        _require(isinstance(angle, dict) and
                 isinstance(angle.get("id"), str) and
                 ID_PATTERN.fullmatch(angle["id"]) is not None and
                 angle["id"] not in seen_angles and
                 isinstance(angle.get("name"), str) and 0 < len(angle["name"]) <= 80 and
                 angle.get("kind") in ANGLE_KINDS, "Invalid or duplicate camera")
        seen_angles.add(angle["id"])
        src = angle.get("source")
        _require(isinstance(src, dict) and src.get("type") in
                 {"local_file", "external_link"}, "Unknown camera media source")
        if src["type"] == "local_file":
            name = src.get("filename")
            _require(isinstance(name, str) and MEDIA_PATTERN.fullmatch(name) is not None and
                     name.lower() not in seen_files, "Unsafe or duplicate media filename")
            seen_files.add(name.lower())
            path = media_dir / name
            # No path normalization, directory traversal, symlinks or special devices.
            try:
                mode = path.lstat().st_mode
            except OSError as error:
                raise ValueError(f"Missing media file: {name}") from error
            _require(stat.S_ISREG(mode), "Media must be a regular non-symlinked file")
            size = path.stat().st_size
            _require(0 < size <= MAX_CLIP_BYTES, "Media exceeds per-file size budget")
            total_bytes += size
            _require(total_bytes <= MAX_SELECTION_BYTES, "Media batch exceeds 160 MB")
            _require(rights["local_playback_authorized"] and
                     rights["derivative_analysis_authorized"],
                     "Local processing not permitted by source rights declaration")
            duration = _duration(path)
            verified = {"type": "local_file", "filename": name,
                        "sha256": _digest(path), "bytes": size,
                        "duration_s": duration}
        else:
            url = src.get("url")
            from urllib.parse import urlsplit

            try:
                parsed = urlsplit(url)
                safe = parsed.scheme == "https" and parsed.hostname is not None and not (
                    parsed.username or parsed.password
                ) and len(url) <= 2048
            except (ValueError, AttributeError, TypeError):
                safe = False
            _require(safe, "External reference must be HTTPS")
            verified = {"type": "external_link", "url": url}
            duration = None
        _check_anchors(angle.get("anchors"), duration)
        _check_evidence(angle.get("evidence"), event_ids)
        enriched.append({
            "id": angle["id"], "name": angle["name"], "kind": angle["kind"],
            "source": verified, "anchors": angle["anchors"], "evidence": angle["evidence"],
        })
    return {
        "schema_version": 1, "data_mode": "RIGHTS_DECLARED_VIDEO_RESEARCH",
        "game_id": game_id, "play_id": play_id, "rights": rights,
        "events": events, "angles": enriched,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--media-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--acknowledge-source-terms", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_source_terms:
        parser.error("Review actual source-use terms and acknowledge them explicitly.")
    source = _read_config(args.config)
    manifest = assemble_manifest(source, args.media_dir)
    payload = json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create, mode 0600, no silent overwrite of an existing record.
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    print(f"AngleIQ manifest created: {len(manifest['angles'])} declared angle(s).")
    print("Local files not copied or uploaded; only their SHA-256 and metadata were written.")
    print("Video rights and event/visibility annotations remain user-declared, not authenticated.")


if __name__ == "__main__":
    main()
