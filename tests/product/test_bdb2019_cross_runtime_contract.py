"""Exercise one REAL code path across the Python exporter and Node preflight.

Everything here is deliberately synthetic. It cannot qualify official NFL
tracking, media rights, or a human-representative 12-play sample.
"""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from player_state_engine.product.bdb2019_batch_replay import export_bdb2019_replay_batch
from player_state_engine.product.bdb2019_source_qualification import (
    SOURCE_FILES,
    file_identifiers,
)

PLAY_IDS = ["938", "2756", *[str(1000 + i) for i in range(10)]]
TERMS = "LOCAL_SYNTHETIC_CROSS_RUNTIME_TEST_ONLY"
REPO_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = (
    REPO_ROOT / "apps" / "gemini-fantasy-console"
    / "scripts" / "privateResearchSession.mjs"
)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _export_twelve(tmp_path: Path) -> tuple[Path, dict]:
    source = tmp_path / "synthetic-source"
    source.mkdir()
    _write_csv(source / "games.csv", [{
        "gameId": "2017090700", "homeTeamAbbr": "NE",
        "visitorTeamAbbr": "KC", "season": "2017", "week": "1",
    }])
    plays = []
    tracking = []
    for index, play_id in enumerate(PLAY_IDS):
        plays.append({
            "gameId": "2017090700", "playId": play_id,
            "possessionTeam": "KC" if index % 2 == 0 else "NE",
            "quarter": "1", "down": "1", "yardsToGo": "10",
            "offenseFormation": "SHOTGUN", "personnel.offense": "1 RB, 1 TE, 3 WR",
        })
        frame_ids = (1, 2, 3) if index % 3 else (1, 2, 4)
        for frame in frame_ids:
            for nflid, team, x, y in (
                ("11", "away", "45", "20"),
                ("22", "home", "47", "23"),
                ("NA", "ball", "46", "21"),
            ):
                # One source row has absent x/y, another falls outside the
                # accepted field. The source observations are still counted.
                if index == 5 and frame == 2 and nflid == "11":
                    x = "NA"
                if index == 7 and frame == 3 and nflid == "22":
                    x = "125"
                tracking.append({
                    "gameId": "2017090700", "playId": play_id,
                    "frame.id": str(frame), "nflId": nflid, "team": team,
                    "x": x, "y": y, "s": "2.2", "dir": "90",
                    "event": "ball_snap" if frame == 1 else "NA",
                    "displayName": "Synthetic only", "jerseyNumber": "11",
                })
    _write_csv(source / "plays.csv", plays)
    _write_csv(source / SOURCE_FILES["tracking"][0], tracking)
    expectations = {
        role: (
            filename,
            file_identifiers(source / filename)["git_blob_sha1"],
            (source / filename).stat().st_size,
        )
        for role, (filename, _, _) in SOURCE_FILES.items()
    }
    output = tmp_path / "private-synthetic-session"
    manifest = export_bdb2019_replay_batch(
        source, output, play_ids=PLAY_IDS,
        license_acknowledged=True, license_identifier=TERMS,
        expectations=expectations,
    )
    assert manifest["qualification_status"] == "NONCANONICAL_FIXTURE_ONLY"
    assert manifest["model_training_authorized"] is False
    assert manifest["source_video_alignment_verified"] is False
    return output, manifest


def _node_preflight(directory: Path) -> subprocess.CompletedProcess[str]:
    script = """
import {inspectPrivateResearchSession} from process.argv[2] ? await import(process.argv[2]) : {};
try {
  const result=await inspectPrivateResearchSession(process.argv[1],{
    expectedPlayCount:12,licenseIdentifier:process.argv[3],
  });
  process.stdout.write(JSON.stringify({
    status:'synthetic_contract_pass',
    source_kind:result.source_kind,
    play_count:result.play_count,
    original_source_bytes_authenticity_confirmed_by_this_preflight:
      result.original_source_bytes_authenticity_confirmed_by_this_preflight,
    sha256s:result.plays.map(p=>p.sha256),
    source_rows:result.plays.map(p=>p.source_rows),
    gaps:result.plays.map(p=>p.missing_source_frames),
  }));
}catch(error){
  process.stderr.write(String(error.message));
  process.exitCode=3;
}
"""
    # Node's input -e argv begins with the session directory at argv[1].
    # Import the exact first-party .mjs module, not a copied mock parser.
    script = script.replace(
        "import {inspectPrivateResearchSession} from process.argv[2] ? await import(process.argv[2]) : {};",
        "const {inspectPrivateResearchSession}=await import(process.argv[2]);",
    )
    return subprocess.run(
        [
            "node", "--input-type=module", "--eval", script,
            str(directory), PREFLIGHT.as_uri(), TERMS,
        ],
        cwd=REPO_ROOT, text=True, capture_output=True,
        timeout=30, check=False,
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_python_export_to_real_node_private_session_contract(tmp_path: Path) -> None:
    out, manifest = _export_twelve(tmp_path)
    result = _node_preflight(out)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "synthetic_contract_pass"
    assert summary["play_count"] == 12
    assert summary["original_source_bytes_authenticity_confirmed_by_this_preflight"] is False
    assert summary["sha256s"] == [entry["sha256"] for entry in manifest["plays"]]
    assert summary["source_rows"] == [entry["source_rows"] for entry in manifest["plays"]]
    assert summary["gaps"] == [entry["missing_source_frames"] for entry in manifest["plays"]]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_exported_replay_tamper_rejected_by_real_node_preflight(tmp_path: Path) -> None:
    out, manifest = _export_twelve(tmp_path)
    target = out / manifest["plays"][3]["file"]
    with target.open("ab") as stream:
        stream.write(b"\n")
    result = _node_preflight(out)
    assert result.returncode != 0
    assert "SHA-256 mismatch" in result.stderr
    assert result.stdout == ""
