from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from player_state_engine.api.evidence_routes import install_evidence_routes
from player_state_engine.product.evidence_artifacts import EvidenceArtifactStore


def _write_artifacts(root: Path) -> Path:
    root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "target": "fantasy_points_ppr",
                "method": "quantile_engine",
                "rows": 100,
                "mean_pinball": 1.2,
                "empirical_80_coverage": 0.81,
            },
            {
                "target": "fantasy_points_ppr",
                "method": "rolling_5",
                "rows": 100,
                "mean_pinball": 1.4,
                "empirical_80_coverage": 0.79,
            },
            {
                "target": "targets",
                "method": "quantile_engine",
                "rows": 80,
                "mean_pinball": 0.8,
                "empirical_80_coverage": 0.80,
            },
        ]
    ).to_csv(root / "method_summary.csv", index=False)
    pd.DataFrame(
        [
            {
                "target": "fantasy_points_ppr",
                "method": "quantile_engine",
                "scope": "position",
                "position": "WR",
                "rows": 50,
                "mean_pinball": 1.1,
            },
            {
                "target": "targets",
                "method": "quantile_engine",
                "scope": "position",
                "position": "WR",
                "rows": 40,
                "mean_pinball": 0.7,
            },
        ]
    ).to_csv(root / "slice_metrics.csv", index=False)
    pd.DataFrame(
        [
            {
                "experiment_id": "fantasy_points_ppr:rolling_5:vs:quantile_engine",
                "target": "fantasy_points_ppr",
                "champion": "quantile_engine",
                "challenger": "rolling_5",
                "paired_rows": 100,
                "pinball_effect_champion_minus_challenger": -0.2,
                "promotion_status": "blocked",
            }
        ]
    ).to_csv(root / "paired_comparisons.csv", index=False)
    pd.DataFrame(
        [
            {
                "experiment_id": "fantasy_points_ppr:rolling_5:vs:quantile_engine",
                "challenger": "rolling_5",
                "champion": "quantile_engine",
                "primary_metric": "mean_pinball",
                "evidence_tier": 2,
                "promoted": False,
                "blockers": "evidence_tier<3",
            }
        ]
    ).to_csv(root / "experiment_ledger.csv", index=False)
    pd.DataFrame(
        [
            {
                "target": "fantasy_points_ppr",
                "method": "rolling_5",
                "control_method": "rolling_5__identity_permutation_control",
                "rows": 100,
                "effect_control_minus_real": 0.3,
                "ci_low": 0.1,
                "ci_high": 0.5,
                "probability_real_improves": 0.99,
                "passed": True,
            }
        ]
    ).to_csv(root / "negative_controls.csv", index=False)
    (root / "run_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "authority": "research_evidence_only",
                "champion_method": "quantile_engine",
                "git_sha": "abc123",
            }
        ),
        encoding="utf-8",
    )
    return root


def test_evidence_artifact_store_exposes_health_and_fail_closed_authority(tmp_path: Path) -> None:
    store = EvidenceArtifactStore(_write_artifacts(tmp_path / "evidence"))

    payload = store.snapshot(target="fantasy_points_ppr")

    assert payload["data_mode"] == "HISTORICAL_BACKTEST"
    assert payload["authority"] == "research_evidence_only"
    assert payload["health"]["available"] is True
    assert payload["health"]["available_count"] == 6
    assert payload["manifest"]["git_sha"] == "abc123"
    assert {row["method"] for row in payload["method_summary"]} == {
        "quantile_engine",
        "rolling_5",
    }
    assert len(payload["paired_comparisons"]) == 1
    assert len(payload["experiment_ledger"]) == 1
    assert len(payload["negative_controls"]) == 1
    assert payload["negative_controls"][0]["passed"] is True
    assert payload["promotion"]["automatic"] is False


def test_evidence_factory_route_filters_targets(tmp_path: Path) -> None:
    root = _write_artifacts(tmp_path / "evidence")
    app = FastAPI()
    install_evidence_routes(app, evidence_factory_root=root)
    client = TestClient(app)

    response = client.get("/v1/model/evidence-factory", params={"target": "targets"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["target"] == "targets"
    assert len(payload["method_summary"]) == 1
    assert payload["method_summary"][0]["target"] == "targets"
    assert payload["paired_comparisons"] == []
    assert payload["experiment_ledger"] == []
    assert payload["negative_controls"] == []


def test_evidence_factory_route_reports_unavailable_without_fabricating_results(tmp_path: Path) -> None:
    app = FastAPI()
    install_evidence_routes(app, evidence_factory_root=tmp_path / "missing")
    client = TestClient(app)

    response = client.get("/v1/model/evidence-factory")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "UNAVAILABLE"
    assert payload["authority"] == "research_evidence_only"
    assert payload["reason"] == "evidence_factory_artifacts_unavailable"
    assert payload["health"]["available"] is False
