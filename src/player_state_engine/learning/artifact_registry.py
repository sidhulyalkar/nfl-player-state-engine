from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

ArtifactAuthority = Literal[
    "research_only",
    "challenger",
    "production_approved",
]


class ArtifactIntegrityError(RuntimeError):
    """Raised when an artifact's bytes or immutable identity do not match its manifest."""


class ArtifactFileRecord(BaseModel):
    role: str
    relative_path: str
    sha256: str
    bytes: int


class ArtifactBundleManifest(BaseModel):
    schema_version: int = 1
    bundle_id: str
    artifact_type: str
    authority: ArtifactAuthority
    activation_eligible: bool = False
    model_id: str | None = None
    target: str | None = None
    code_sha: str | None = None
    config_sha256: str | None = None
    source_cutoff_utc: str | None = None
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    files: list[ArtifactFileRecord]
    metadata: dict[str, Any] = Field(default_factory=dict)

    def identity_payload(self) -> dict[str, Any]:
        """Return the immutable fields used to derive the content-addressed bundle ID."""

        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "authority": self.authority,
            "activation_eligible": self.activation_eligible,
            "model_id": self.model_id,
            "target": self.target,
            "code_sha": self.code_sha,
            "config_sha256": self.config_sha256,
            "source_cutoff_utc": self.source_cutoff_utc,
            "files": [record.model_dump(mode="json") for record in self.files],
            "metadata": self.metadata,
        }


class ChampionRecord(BaseModel):
    bundle_id: str
    approved_by: str
    approved_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    note: str | None = None


class ChampionPointer(BaseModel):
    schema_version: int = 1
    champions: dict[str, ChampionRecord] = Field(default_factory=dict)


def sha256_file(path: str | Path) -> str:
    candidate = Path(path)
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _bundle_id(identity_payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(identity_payload)).hexdigest()


def _relative_artifact_path(root: Path, path: Path) -> str:
    root_resolved = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Artifact {resolved} is outside bundle root {root_resolved}.") from exc
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return relative.as_posix()


def build_artifact_bundle(
    bundle_root: str | Path,
    files: dict[str, str | Path],
    *,
    artifact_type: str,
    authority: ArtifactAuthority,
    activation_eligible: bool = False,
    model_id: str | None = None,
    target: str | None = None,
    code_sha: str | None = None,
    config_sha256: str | None = None,
    source_cutoff_utc: str | None = None,
    metadata: dict[str, Any] | None = None,
    created_at_utc: datetime | None = None,
) -> ArtifactBundleManifest:
    """Build a content-addressed manifest over immutable artifact bytes.

    ``bundle_root`` is the directory that will be transported to durable storage. Every artifact
    must live below it so manifests remain relocatable. The bundle ID depends on file hashes and
    scientific identity, never filesystem mtimes or the time the manifest happened to be written.
    """

    root = Path(bundle_root)
    if not files:
        raise ValueError("An artifact bundle requires at least one file.")
    if not artifact_type.strip():
        raise ValueError("artifact_type must be non-empty.")
    if activation_eligible and authority != "production_approved":
        raise ValueError("Only production_approved bundles may be activation eligible.")

    records: list[ArtifactFileRecord] = []
    for role, raw_path in sorted(files.items()):
        if not str(role).strip():
            raise ValueError("Artifact roles must be non-empty.")
        path = Path(raw_path)
        relative = _relative_artifact_path(root, path)
        records.append(
            ArtifactFileRecord(
                role=str(role),
                relative_path=relative,
                sha256=sha256_file(path),
                bytes=path.stat().st_size,
            )
        )
    if len({record.role for record in records}) != len(records):
        raise ValueError("Artifact roles must be unique.")
    if len({record.relative_path for record in records}) != len(records):
        raise ValueError("Each artifact file may appear only once in a bundle.")

    provisional = ArtifactBundleManifest(
        bundle_id="pending",
        artifact_type=artifact_type.strip(),
        authority=authority,
        activation_eligible=bool(activation_eligible),
        model_id=model_id,
        target=target,
        code_sha=code_sha,
        config_sha256=config_sha256,
        source_cutoff_utc=source_cutoff_utc,
        created_at_utc=created_at_utc or datetime.now(UTC),
        files=records,
        metadata=dict(metadata or {}),
    )
    provisional.bundle_id = _bundle_id(provisional.identity_payload())
    return provisional


def verify_artifact_bundle(
    manifest: ArtifactBundleManifest,
    bundle_root: str | Path,
) -> dict[str, Any]:
    root = Path(bundle_root)
    expected_id = _bundle_id(manifest.identity_payload())
    failures: list[str] = []
    if manifest.bundle_id != expected_id:
        failures.append("bundle_id_mismatch")

    file_results: list[dict[str, Any]] = []
    for record in manifest.files:
        path = root / record.relative_path
        available = path.is_file()
        actual_sha = sha256_file(path) if available else None
        actual_bytes = path.stat().st_size if available else None
        matches = (
            available
            and actual_sha == record.sha256
            and actual_bytes == record.bytes
        )
        if not available:
            failures.append(f"missing:{record.role}")
        elif actual_sha != record.sha256:
            failures.append(f"sha256_mismatch:{record.role}")
        elif actual_bytes != record.bytes:
            failures.append(f"size_mismatch:{record.role}")
        file_results.append(
            {
                "role": record.role,
                "relative_path": record.relative_path,
                "available": available,
                "expected_sha256": record.sha256,
                "actual_sha256": actual_sha,
                "expected_bytes": record.bytes,
                "actual_bytes": actual_bytes,
                "integrity_match": bool(matches),
            }
        )

    return {
        "bundle_id": manifest.bundle_id,
        "integrity_verified": not failures,
        "failures": failures,
        "files": file_results,
    }


def require_valid_bundle(
    manifest: ArtifactBundleManifest,
    bundle_root: str | Path,
) -> None:
    health = verify_artifact_bundle(manifest, bundle_root)
    if not health["integrity_verified"]:
        raise ArtifactIntegrityError(
            f"Artifact bundle {manifest.bundle_id} failed integrity checks: {health['failures']}"
        )


def _bundle_manifest_path(registry_root: Path, bundle_id: str) -> Path:
    return registry_root / "bundles" / f"{bundle_id}.json"


def save_artifact_bundle_manifest(
    manifest: ArtifactBundleManifest,
    registry_root: str | Path,
) -> Path:
    """Persist a manifest once. Existing bundle IDs are immutable."""

    root = Path(registry_root)
    path = _bundle_manifest_path(root, manifest.bundle_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = manifest.model_dump_json(indent=2)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
    except FileExistsError:
        existing = ArtifactBundleManifest.model_validate_json(path.read_text(encoding="utf-8"))
        if existing.identity_payload() != manifest.identity_payload():
            raise ArtifactIntegrityError(
                f"Bundle ID {manifest.bundle_id} already exists with a different immutable identity."
            )
    return path


def load_artifact_bundle_manifest(
    registry_root: str | Path,
    bundle_id: str,
) -> ArtifactBundleManifest:
    path = _bundle_manifest_path(Path(registry_root), bundle_id)
    if not path.is_file():
        raise FileNotFoundError(path)
    manifest = ArtifactBundleManifest.model_validate_json(path.read_text(encoding="utf-8"))
    expected_id = _bundle_id(manifest.identity_payload())
    if manifest.bundle_id != bundle_id or expected_id != bundle_id:
        raise ArtifactIntegrityError(f"Manifest identity mismatch for requested bundle {bundle_id}.")
    return manifest


def _champion_path(registry_root: str | Path) -> Path:
    return Path(registry_root) / "champions.json"


def load_champion_pointer(registry_root: str | Path) -> ChampionPointer:
    path = _champion_path(registry_root)
    if not path.is_file():
        return ChampionPointer()
    return ChampionPointer.model_validate_json(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(payload + "\n", encoding="utf-8")
    temporary.replace(path)


def promote_artifact_bundle(
    registry_root: str | Path,
    bundle_root: str | Path,
    *,
    target: str,
    bundle_id: str,
    approved_by: str,
    note: str | None = None,
) -> ChampionPointer:
    """Move a champion pointer only after explicit human/manual approval and byte verification."""

    if not target.strip():
        raise ValueError("target must be non-empty.")
    if not approved_by.strip():
        raise ValueError("approved_by is required; automatic promotion is prohibited.")

    manifest = load_artifact_bundle_manifest(registry_root, bundle_id)
    require_valid_bundle(manifest, bundle_root)
    if manifest.authority != "production_approved":
        raise PermissionError(
            f"Bundle {bundle_id} has authority={manifest.authority}; production_approved is required."
        )
    if not manifest.activation_eligible:
        raise PermissionError(f"Bundle {bundle_id} is not activation eligible.")
    if manifest.target and manifest.target != target:
        raise ValueError(
            f"Bundle target {manifest.target!r} does not match champion target {target!r}."
        )

    pointer = load_champion_pointer(registry_root)
    pointer.champions[target] = ChampionRecord(
        bundle_id=bundle_id,
        approved_by=approved_by.strip(),
        note=note,
    )
    _atomic_write_json(_champion_path(registry_root), pointer.model_dump_json(indent=2))
    return pointer


def resolve_champion_bundle(
    registry_root: str | Path,
    bundle_root: str | Path,
    target: str,
) -> ArtifactBundleManifest:
    pointer = load_champion_pointer(registry_root)
    record = pointer.champions.get(target)
    if record is None:
        raise KeyError(f"No champion bundle registered for target {target!r}.")
    manifest = load_artifact_bundle_manifest(registry_root, record.bundle_id)
    require_valid_bundle(manifest, bundle_root)
    if manifest.target and manifest.target != target:
        raise ArtifactIntegrityError(
            f"Champion pointer target {target!r} resolves to bundle target {manifest.target!r}."
        )
    return manifest
