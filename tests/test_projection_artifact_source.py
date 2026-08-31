from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from player_state_engine.data.io import write_table
from player_state_engine.learning.artifact_registry import (
    ArtifactIntegrityError,
    build_artifact_bundle,
    promote_artifact_bundle,
    save_artifact_bundle_manifest,
)
from player_state_engine.product.projection_artifact_source import ProjectionArtifactSource

TARGET = "preseason_multicontract_player_values_2026"


def _product() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": "P1",
                "player_name": "Player One",
                "position": "RB",
                "season_points_q10": 100.0,
                "season_points_q50": 150.0,
                "season_points_q90": 200.0,
                "scoring_contract_id": "contract-a",
                "decision_quantile_policy": "qualified_distribution",
            }
        ]
    )


def _approved_bundle(tmp_path: Path) -> tuple[Path, Path, str, Path]:
    bundle_root = tmp_path / "bundle"
    registry_root = tmp_path / "registry"
    values_path = write_table(_product(), bundle_root / "product_player_values.csv")
    evidence_path = bundle_root / "approval.json"
    evidence_path.write_text('{"approved": true}\n', encoding="utf-8")
    manifest = build_artifact_bundle(
        bundle_root,
        {"player_values": values_path, "approval_evidence": evidence_path},
        artifact_type="preseason_multicontract_player_values_production",
        authority="production_approved",
        activation_eligible=True,
        model_id="preseason_direct_league_score_v017",
        target=TARGET,
        code_sha="abc123",
        source_cutoff_utc="2026-08-31T16:00:00+00:00",
    )
    save_artifact_bundle_manifest(manifest, registry_root)
    promote_artifact_bundle(
        registry_root,
        bundle_root,
        target=TARGET,
        bundle_id=manifest.bundle_id,
        approved_by="release-owner",
    )
    return bundle_root, registry_root, manifest.bundle_id, values_path


def test_champion_source_resolves_verified_exact_bytes(tmp_path: Path) -> None:
    bundle_root, registry_root, bundle_id, values_path = _approved_bundle(tmp_path)
    source = ProjectionArtifactSource(
        mode="champion",
        registry_root=registry_root,
        bundle_root=bundle_root,
        champion_target=TARGET,
    )

    snapshot = source.load()

    assert snapshot.path == values_path
    assert snapshot.source_mode == "champion"
    assert snapshot.authority == "production_approved"
    assert snapshot.integrity_verified is True
    assert snapshot.bundle_id == bundle_id
    assert snapshot.target == TARGET
    assert snapshot.model_id == "preseason_direct_league_score_v017"
    assert snapshot.frame.iloc[0]["player_id"] == "P1"


def test_champion_source_detects_post_promotion_tampering(tmp_path: Path) -> None:
    bundle_root, registry_root, _bundle_id, values_path = _approved_bundle(tmp_path)
    values_path.write_text("player_id\nEVIL\n", encoding="utf-8")
    source = ProjectionArtifactSource(
        mode="champion",
        registry_root=registry_root,
        bundle_root=bundle_root,
        champion_target=TARGET,
    )

    with pytest.raises(ArtifactIntegrityError, match="failed integrity checks"):
        source.load()


def test_champion_mode_never_falls_back_to_path(tmp_path: Path) -> None:
    path = write_table(_product(), tmp_path / "fallback.csv")
    source = ProjectionArtifactSource(
        mode="champion",
        path=path,
        registry_root=tmp_path / "registry",
        bundle_root=tmp_path / "missing-bundle",
        champion_target=TARGET,
    )

    with pytest.raises(KeyError, match="No champion bundle"):
        source.load()


def test_explicit_path_is_unverified_even_when_bytes_are_valid(tmp_path: Path) -> None:
    path = write_table(_product(), tmp_path / "dev.csv")
    source = ProjectionArtifactSource(mode="path", path=path)

    snapshot = source.load()

    assert snapshot.source_mode == "path"
    assert snapshot.authority == "path_unverified"
    assert snapshot.integrity_verified is False
    assert snapshot.bundle_id is None


def test_champion_requires_exact_player_values_role(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    registry_root = tmp_path / "registry"
    wrong_path = write_table(_product(), bundle_root / "wrong.csv")
    manifest = build_artifact_bundle(
        bundle_root,
        {"not_player_values": wrong_path},
        artifact_type="production",
        authority="production_approved",
        activation_eligible=True,
        target=TARGET,
    )
    save_artifact_bundle_manifest(manifest, registry_root)
    promote_artifact_bundle(
        registry_root,
        bundle_root,
        target=TARGET,
        bundle_id=manifest.bundle_id,
        approved_by="release-owner",
    )
    source = ProjectionArtifactSource(
        mode="champion",
        registry_root=registry_root,
        bundle_root=bundle_root,
        champion_target=TARGET,
    )

    with pytest.raises(ValueError, match="exactly one player_values"):
        source.load()
