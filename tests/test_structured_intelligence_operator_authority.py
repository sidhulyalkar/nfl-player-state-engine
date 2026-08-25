from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from player_state_engine.state_graph.experiments import EvidenceTier


def test_tier_two_operator_requires_separate_source_coverage_artifact(tmp_path: Path) -> None:
    provenance = tmp_path / "provenance.json"
    provenance.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "authority": "research_evidence_only",
                "evidence_tier": int(EvidenceTier.MULTI_SEASON_ISOLATED),
                "frozen_sample_id": "frozen-official-v1",
                "point_in_time_verified": True,
                "source_coverage_point_in_time_verified": True,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_structured_intelligence_ablation.py",
            "--features",
            str(tmp_path / "missing-features.parquet"),
            "--ledger-root",
            str(tmp_path / "missing-ledger"),
            "--evidence-provenance-manifest",
            str(provenance),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "requires a separately hashed --source-coverage artifact" in result.stderr
