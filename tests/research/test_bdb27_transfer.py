"""Private scientific linkage requires matching source hashes and preserves abstention."""
from __future__ import annotations

import json

import pytest

from scripts.build_bdb27_transfer_audit import build
from player_state_engine.research.bdb27_nfl import run_rookie_game_audit
from player_state_engine.research.bdb27_qualification import QualificationConfig, qualify_directory
from tests.research.test_bdb27_nfl import games, nfl_frames
from tests.research.test_bdb27_qualification import attempt, players
import pandas as pd


def test_audit_linkage_never_mistakes_synthetic_profiles_for_validated_outcomes(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    players().to_csv(raw / "players.csv", index=False)
    games().to_csv(raw / "games.csv", index=False)
    pd.concat([attempt(i, side=1 if i < 4 else -1) for i in range(8)]).to_csv(
        raw / "combine_tracking.csv", index=False)
    nfl_frames().to_csv(raw / "game_tracking_2023.csv", index=False)
    c, n, out = tmp_path / "combine", tmp_path / "nfl2023", tmp_path / "transfer"
    qualify_directory(raw, c, QualificationConfig(1), source_rights_acknowledged=True)
    run_rookie_game_audit(raw, n, year=2023, position="DB", config=QualificationConfig(1),
                          rights_acknowledged=True)
    summary = build(c, [n], out, position="DB")
    assert summary["distinct_paired_players"] == 1
    assert summary["paired_player_drill_rows"] == 1
    assert summary["pre_registered_outcome_validation_complete"] is False
    assert summary["sign_comparisons_validated"] is False
    assert (out / "transfer_coverage_PRIVATE.csv").is_file()
    assert json.loads((out / "transfer_summary.json").read_text())["authority"] == "RESEARCH_ONLY_NO_PROMOTION"
    with pytest.raises(ValueError, match="duplicate NFL rookie-year"):
        build(c, [n, n], tmp_path / "invalid")


def test_player_hash_mismatch_fails_before_linkage(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    players().to_csv(raw / "players.csv", index=False)
    games().to_csv(raw / "games.csv", index=False)
    pd.concat([attempt(i, side=1 if i < 4 else -1) for i in range(8)]).to_csv(
        raw / "combine_tracking.csv", index=False)
    nfl_frames().to_csv(raw / "game_tracking_2023.csv", index=False)
    c, n = tmp_path / "combine", tmp_path / "nfl"
    qualify_directory(raw, c, QualificationConfig(1), source_rights_acknowledged=True)
    run_rookie_game_audit(raw, n, year=2023, position="DB", config=QualificationConfig(1),
                          rights_acknowledged=True)
    p = n / "nfl_2023_DB_manifest.json"
    doc = json.loads(p.read_text())
    doc["source_files"]["players.csv"] = "f" * 64
    p.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="SHA mismatch"):
        build(c, [n], tmp_path / "refuse")
