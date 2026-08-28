from __future__ import annotations

from pathlib import Path

import pytest

from player_state_engine.learning.artifact_registry import (
    ArtifactIntegrityError,
    build_artifact_bundle,
    load_champion_pointer,
    promote_artifact_bundle,
    resolve_champion_bundle,
    save_artifact_bundle_manifest,
    verify_artifact_bundle,
)


def _bundle_files(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    model = root / "model.joblib"
    projections = root / "projections.parquet"
    model.write_bytes(b"model-v1")
    projections.write_bytes(b"projection-v1")
    return {"model": model, "projections": projections}


def test_bundle_identity_depends_on_bytes_not_write_time(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    files = _bundle_files(bundle_root)
    first = build_artifact_bundle(
        bundle_root,
        files,
        artifact_type="weekly_projection",
        authority="challenger",
        model_id="m1",
        target="fantasy_points_ppr",
        code_sha="abc",
        config_sha256="def",
    )
    second = build_artifact_bundle(
        bundle_root,
        files,
        artifact_type="weekly_projection",
        authority="challenger",
        model_id="m1",
        target="fantasy_points_ppr",
        code_sha="abc",
        config_sha256="def",
    )
    assert first.bundle_id == second.bundle_id

    files["model"].write_bytes(b"model-v2")
    changed = build_artifact_bundle(
        bundle_root,
        files,
        artifact_type="weekly_projection",
        authority="challenger",
        model_id="m1",
        target="fantasy_points_ppr",
        code_sha="abc",
        config_sha256="def",
    )
    assert changed.bundle_id != first.bundle_id


def test_bundle_rejects_paths_outside_transport_root(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"not-in-bundle")
    with pytest.raises(ValueError, match="outside bundle root"):
        build_artifact_bundle(
            root,
            {"model": outside},
            artifact_type="weekly_projection",
            authority="challenger",
        )


def test_tampered_bytes_fail_closed(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    registry_root = tmp_path / "registry"
    files = _bundle_files(bundle_root)
    manifest = build_artifact_bundle(
        bundle_root,
        files,
        artifact_type="weekly_projection",
        authority="challenger",
    )
    save_artifact_bundle_manifest(manifest, registry_root)
    assert verify_artifact_bundle(manifest, bundle_root)["integrity_verified"] is True

    files["model"].write_bytes(b"tampered")
    health = verify_artifact_bundle(manifest, bundle_root)
    assert health["integrity_verified"] is False
    assert "sha256_mismatch:model" in health["failures"]


def test_research_or_challenger_bundle_cannot_be_promoted(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    registry_root = tmp_path / "registry"
    files = _bundle_files(bundle_root)
    manifest = build_artifact_bundle(
        bundle_root,
        files,
        artifact_type="preseason_projection",
        authority="challenger",
        target="fantasy_points_ppr",
    )
    save_artifact_bundle_manifest(manifest, registry_root)

    with pytest.raises(PermissionError, match="production_approved"):
        promote_artifact_bundle(
            registry_root,
            bundle_root,
            target="fantasy_points_ppr",
            bundle_id=manifest.bundle_id,
            approved_by="reviewer",
        )
    assert load_champion_pointer(registry_root).champions == {}


def test_manual_promotion_requires_activation_eligibility_and_verifies_bundle(
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle"
    registry_root = tmp_path / "registry"
    files = _bundle_files(bundle_root)
    manifest = build_artifact_bundle(
        bundle_root,
        files,
        artifact_type="weekly_projection",
        authority="production_approved",
        activation_eligible=True,
        model_id="m-prod",
        target="fantasy_points_ppr",
        code_sha="code-sha",
        config_sha256="config-sha",
        source_cutoff_utc="2026-08-28T20:00:00+00:00",
    )
    save_artifact_bundle_manifest(manifest, registry_root)

    with pytest.raises(ValueError, match="approved_by"):
        promote_artifact_bundle(
            registry_root,
            bundle_root,
            target="fantasy_points_ppr",
            bundle_id=manifest.bundle_id,
            approved_by="",
        )

    pointer = promote_artifact_bundle(
        registry_root,
        bundle_root,
        target="fantasy_points_ppr",
        bundle_id=manifest.bundle_id,
        approved_by="manual-review",
        note="Frozen evidence gates passed.",
    )
    assert pointer.champions["fantasy_points_ppr"].bundle_id == manifest.bundle_id
    resolved = resolve_champion_bundle(
        registry_root,
        bundle_root,
        "fantasy_points_ppr",
    )
    assert resolved.bundle_id == manifest.bundle_id

    files["projections"].write_bytes(b"changed-after-promotion")
    with pytest.raises(ArtifactIntegrityError, match="integrity checks"):
        resolve_champion_bundle(registry_root, bundle_root, "fantasy_points_ppr")
