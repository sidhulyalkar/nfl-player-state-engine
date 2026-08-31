from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from player_state_engine.api.operational import create_app
from player_state_engine.data.io import write_table
from player_state_engine.learning.artifact_registry import (
    build_artifact_bundle,
    promote_artifact_bundle,
    save_artifact_bundle_manifest,
)
from player_state_engine.product.projection_artifact_source import DEFAULT_CHAMPION_TARGET


def _production_bundle(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    bundle_root = tmp_path / "bundle"
    registry_root = tmp_path / "registry"
    product = pd.DataFrame(
        [
            {
                "player_id": "P1",
                "player_name": "Player One",
                "position": "RB",
                "season_points_q10": 100.0,
                "season_points_q50": 150.0,
                "season_points_q90": 200.0,
                "model_version": "preseason_direct_league_score_v017",
                "scoring_contract_id": "contract-a",
                "decision_quantile_policy": "qualified_distribution",
                "artifact_authority": "production_approved",
            }
        ]
    )
    values_path = write_table(product, bundle_root / "product_player_values.csv")
    approval_path = bundle_root / "approval_evidence.json"
    approval_path.write_text('{"approved_by":"release-owner"}\n', encoding="utf-8")
    manifest = build_artifact_bundle(
        bundle_root,
        {"player_values": values_path, "approval_evidence": approval_path},
        artifact_type="preseason_multicontract_player_values_production",
        authority="production_approved",
        activation_eligible=True,
        model_id="preseason_direct_league_score_v017",
        target=DEFAULT_CHAMPION_TARGET,
        code_sha="release-sha",
        source_cutoff_utc="2026-08-31T16:00:00+00:00",
    )
    save_artifact_bundle_manifest(manifest, registry_root)
    promote_artifact_bundle(
        registry_root,
        bundle_root,
        target=DEFAULT_CHAMPION_TARGET,
        bundle_id=manifest.bundle_id,
        approved_by="release-owner",
    )
    return bundle_root, registry_root, values_path, manifest.bundle_id


def test_operational_health_exposes_verified_champion_identity(
    tmp_path: Path, monkeypatch
) -> None:
    bundle_root, registry_root, _values_path, bundle_id = _production_bundle(tmp_path)
    monkeypatch.setenv("PSE_PROJECTION_SOURCE_MODE", "champion")
    monkeypatch.setenv("PSE_ARTIFACT_REGISTRY_ROOT", str(registry_root))
    monkeypatch.setenv("PSE_PRODUCTION_BUNDLE_ROOT", str(bundle_root))
    monkeypatch.setenv("PSE_PROJECTION_CHAMPION_TARGET", DEFAULT_CHAMPION_TARGET)

    app = create_app(store_root=tmp_path / "leagues")
    payload = TestClient(app).get("/health").json()

    assert payload["projection_source_mode"] == "champion"
    assert payload["projection_authority"] == "production_approved"
    assert payload["projection_integrity_verified"] is True
    assert payload["projection_bundle_id"] == bundle_id
    assert payload["projection_target"] == DEFAULT_CHAMPION_TARGET


def test_operational_guard_blocks_requests_after_champion_bytes_change(
    tmp_path: Path, monkeypatch
) -> None:
    bundle_root, registry_root, values_path, _bundle_id = _production_bundle(tmp_path)
    monkeypatch.setenv("PSE_PROJECTION_SOURCE_MODE", "champion")
    monkeypatch.setenv("PSE_ARTIFACT_REGISTRY_ROOT", str(registry_root))
    monkeypatch.setenv("PSE_PRODUCTION_BUNDLE_ROOT", str(bundle_root))

    app = create_app(store_root=tmp_path / "leagues")
    client = TestClient(app)
    assert client.get("/v1/leagues").status_code == 200

    values_path.write_text("player_id\nTAMPERED\n", encoding="utf-8")

    blocked = client.get("/v1/leagues")
    assert blocked.status_code == 503
    assert blocked.json()["projection_source_mode"] == "champion"
    assert blocked.json()["projection_integrity_verified"] is False
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert health.json()["projection_integrity_verified"] is False


def test_explicit_projection_path_remains_dev_mode_even_with_champion_env(
    tmp_path: Path, monkeypatch
) -> None:
    _bundle_root, _registry_root, _values_path, _bundle_id = _production_bundle(tmp_path)
    explicit = write_table(
        pd.DataFrame(
            [
                {
                    "player_id": "DEV",
                    "player_name": "Dev Player",
                    "position": "WR",
                    "season_points_q10": 1.0,
                    "season_points_q50": 2.0,
                    "season_points_q90": 3.0,
                }
            ]
        ),
        tmp_path / "dev.csv",
    )
    monkeypatch.setenv("PSE_PROJECTION_SOURCE_MODE", "champion")

    app = create_app(store_root=tmp_path / "leagues", projections_path=explicit)
    payload = TestClient(app).get("/health").json()

    assert payload["projection_source_mode"] == "path"
    assert payload["projection_authority"] == "path_unverified"
    assert payload["projection_integrity_verified"] is False
