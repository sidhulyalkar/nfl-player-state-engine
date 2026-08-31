from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from player_state_engine.learning.approval_derivation import derive_production_approved_bundle
from player_state_engine.learning.artifact_registry import (
    ArtifactIntegrityError,
    build_artifact_bundle,
    load_champion_pointer,
    save_artifact_bundle_manifest,
    verify_artifact_bundle,
)


def _registered_bundle(
    tmp_path: Path,
    *,
    authority: str = "challenger",
    target: str | None = "preseason_multicontract_player_values_2026",
    metadata: dict[str, object] | None = None,
):
    bundle_root = tmp_path / "bundle"
    registry_root = tmp_path / "registry"
    bundle_root.mkdir()
    values = bundle_root / "product_player_values.csv"
    evidence = bundle_root / "qualification.json"
    values.write_text("player_id,value\nP1,10\n", encoding="utf-8")
    evidence.write_text('{"approved": true}\n', encoding="utf-8")
    manifest = build_artifact_bundle(
        bundle_root,
        {"player_values": values, "qualification_evidence": evidence},
        artifact_type="preseason_multicontract_player_values_candidate",
        authority=authority,  # type: ignore[arg-type]
        activation_eligible=False,
        model_id="preseason_direct_league_score_v017",
        target=target,
        code_sha="abc123",
        source_cutoff_utc="2026-08-31T07:00:00+00:00",
        metadata={"automatic_promotion": False, **dict(metadata or {})},
    )
    save_artifact_bundle_manifest(manifest, registry_root)
    return bundle_root, registry_root, manifest


def test_manual_approval_derives_new_authority_over_exact_same_bytes(tmp_path: Path) -> None:
    bundle_root, registry_root, challenger = _registered_bundle(tmp_path)
    approved_at = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)

    production = derive_production_approved_bundle(
        registry_root,
        bundle_root,
        challenger_bundle_id=challenger.bundle_id,
        approved_by="release-reviewer",
        approval_note="Reviewed exact rehearsal evidence",
        approved_at_utc=approved_at,
    )

    assert production.bundle_id != challenger.bundle_id
    assert production.authority == "production_approved"
    assert production.activation_eligible is True
    assert production.target == challenger.target
    assert [(f.role, f.relative_path, f.sha256, f.bytes) for f in production.files] == [
        (f.role, f.relative_path, f.sha256, f.bytes) for f in challenger.files
    ]
    approval = production.metadata["manual_production_approval"]
    assert approval["source_challenger_bundle_id"] == challenger.bundle_id
    assert approval["approved_by"] == "release-reviewer"
    assert approval["champion_pointer_moved"] is False
    assert verify_artifact_bundle(production, bundle_root)["integrity_verified"] is True
    assert load_champion_pointer(registry_root).champions == {}


def test_approval_requires_explicit_approver(tmp_path: Path) -> None:
    bundle_root, registry_root, challenger = _registered_bundle(tmp_path)
    with pytest.raises(ValueError, match="approved_by is required"):
        derive_production_approved_bundle(
            registry_root,
            bundle_root,
            challenger_bundle_id=challenger.bundle_id,
            approved_by="   ",
        )


def test_approval_refuses_non_challenger_source(tmp_path: Path) -> None:
    bundle_root, registry_root, source = _registered_bundle(
        tmp_path,
        authority="research_only",
    )
    with pytest.raises(PermissionError, match="challenger is required"):
        derive_production_approved_bundle(
            registry_root,
            bundle_root,
            challenger_bundle_id=source.bundle_id,
            approved_by="reviewer",
        )


def test_approval_refuses_reserved_approval_metadata(tmp_path: Path) -> None:
    bundle_root, registry_root, challenger = _registered_bundle(
        tmp_path,
        metadata={"manual_production_approval": {"forged": True}},
    )
    with pytest.raises(ArtifactIntegrityError, match="reserved key"):
        derive_production_approved_bundle(
            registry_root,
            bundle_root,
            challenger_bundle_id=challenger.bundle_id,
            approved_by="reviewer",
        )


def test_approval_detects_challenger_tamper_before_derivation(tmp_path: Path) -> None:
    bundle_root, registry_root, challenger = _registered_bundle(tmp_path)
    (bundle_root / "product_player_values.csv").write_text(
        "player_id,value\nP1,999\n",
        encoding="utf-8",
    )
    with pytest.raises(ArtifactIntegrityError, match="failed integrity checks"):
        derive_production_approved_bundle(
            registry_root,
            bundle_root,
            challenger_bundle_id=challenger.bundle_id,
            approved_by="reviewer",
        )
