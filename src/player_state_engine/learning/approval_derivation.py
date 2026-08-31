from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from player_state_engine.learning.artifact_registry import (
    ArtifactBundleManifest,
    ArtifactIntegrityError,
    build_artifact_bundle,
    load_artifact_bundle_manifest,
    require_valid_bundle,
    save_artifact_bundle_manifest,
    verify_artifact_bundle,
)

_APPROVAL_METADATA_KEY = "manual_production_approval"


def derive_production_approved_bundle(
    registry_root: str | Path,
    bundle_root: str | Path,
    *,
    challenger_bundle_id: str,
    approved_by: str,
    approval_note: str | None = None,
    approved_at_utc: datetime | None = None,
) -> ArtifactBundleManifest:
    """Derive production authority over exact challenger bytes after explicit human approval.

    This operation intentionally does **not** move a champion pointer. The returned production
    manifest has a new immutable bundle identity because authority and approval provenance are part
    of the manifest identity, while every artifact role/path/hash/byte count must remain identical
    to the reviewed challenger. Activation therefore remains a separate, explicit registry action.
    """

    approver = approved_by.strip()
    if not approver:
        raise ValueError("approved_by is required; automatic approval is prohibited")

    approved_at = approved_at_utc or datetime.now(UTC)
    if approved_at.tzinfo is None:
        raise ValueError("approved_at_utc must be timezone-aware")
    approved_at = approved_at.astimezone(UTC)

    challenger = load_artifact_bundle_manifest(registry_root, challenger_bundle_id)
    require_valid_bundle(challenger, bundle_root)
    if challenger.authority != "challenger":
        raise PermissionError(
            f"Bundle {challenger_bundle_id} has authority={challenger.authority}; challenger is required"
        )
    if challenger.activation_eligible:
        raise ArtifactIntegrityError("A challenger may not already be activation eligible")
    if not challenger.target:
        raise ValueError("The challenger must declare an exact target before production approval")
    if _APPROVAL_METADATA_KEY in challenger.metadata:
        raise ArtifactIntegrityError(
            f"Challenger metadata already contains reserved key {_APPROVAL_METADATA_KEY!r}"
        )

    root = Path(bundle_root)
    files = {record.role: root / record.relative_path for record in challenger.files}
    metadata = {
        **challenger.metadata,
        "automatic_promotion": False,
        _APPROVAL_METADATA_KEY: {
            "schema_version": 1,
            "source_challenger_bundle_id": challenger.bundle_id,
            "approved_by": approver,
            "approved_at_utc": approved_at.isoformat(),
            "note": approval_note,
            "champion_pointer_moved": False,
        },
    }
    production = build_artifact_bundle(
        root,
        files,
        artifact_type=challenger.artifact_type,
        authority="production_approved",
        activation_eligible=True,
        model_id=challenger.model_id,
        target=challenger.target,
        code_sha=challenger.code_sha,
        config_sha256=challenger.config_sha256,
        source_cutoff_utc=challenger.source_cutoff_utc,
        metadata=metadata,
        created_at_utc=approved_at,
    )

    challenger_bytes = [
        (record.role, record.relative_path, record.sha256, record.bytes)
        for record in challenger.files
    ]
    production_bytes = [
        (record.role, record.relative_path, record.sha256, record.bytes)
        for record in production.files
    ]
    if production_bytes != challenger_bytes:
        raise ArtifactIntegrityError(
            "Production approval derivation changed artifact bytes or artifact-role identity"
        )
    if production.bundle_id == challenger.bundle_id:
        raise ArtifactIntegrityError("Production approval must derive a distinct immutable bundle identity")

    save_artifact_bundle_manifest(production, registry_root)
    health = verify_artifact_bundle(production, root)
    if not health["integrity_verified"]:
        raise ArtifactIntegrityError(
            f"Derived production bundle failed byte verification: {health['failures']}"
        )
    return production
