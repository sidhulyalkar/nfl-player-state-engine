from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from player_state_engine.data.io import read_table
from player_state_engine.learning.artifact_registry import (
    ArtifactBundleManifest,
    resolve_champion_bundle,
)

DEFAULT_PROJECTION_PATH = Path("artifacts/predictions/product_player_values.csv")
DEFAULT_CHAMPION_TARGET = "preseason_multicontract_player_values_2026"
ProjectionSourceMode = Literal["path", "champion"]


@dataclass(frozen=True, slots=True)
class ProjectionArtifactSnapshot:
    frame: pd.DataFrame
    path: Path
    source_mode: ProjectionSourceMode
    authority: str
    integrity_verified: bool
    target: str | None = None
    bundle_id: str | None = None
    model_id: str | None = None
    code_sha: str | None = None
    source_cutoff_utc: str | None = None

    def trust_metadata(self) -> dict[str, object]:
        return {
            "projection_source_mode": self.source_mode,
            "projection_authority": self.authority,
            "projection_integrity_verified": self.integrity_verified,
            "projection_target": self.target,
            "projection_bundle_id": self.bundle_id,
            "projection_model_id": self.model_id,
            "projection_code_sha": self.code_sha,
            "projection_source_cutoff_utc": self.source_cutoff_utc,
            "projection_artifact_path": str(self.path),
        }


class ProjectionArtifactSource:
    """Resolve projection bytes from either an explicit dev path or a verified champion.

    ``champion`` mode is intentionally fail-closed. It never falls back to
    ``PSE_PROJECTIONS_PATH`` if the champion pointer, manifest, target, authority, bytes, or
    required ``player_values`` role are invalid. Path mode exists for development, fixtures, and
    historical compatibility only and never receives production-approved authority.
    """

    def __init__(
        self,
        *,
        mode: ProjectionSourceMode,
        path: str | Path | None = None,
        registry_root: str | Path | None = None,
        bundle_root: str | Path | None = None,
        champion_target: str = DEFAULT_CHAMPION_TARGET,
    ) -> None:
        if mode not in {"path", "champion"}:
            raise ValueError(f"Unsupported projection source mode: {mode!r}")
        self.mode: ProjectionSourceMode = mode
        self.path = Path(path or DEFAULT_PROJECTION_PATH)
        self.registry_root = Path(registry_root) if registry_root else None
        self.bundle_root = Path(bundle_root) if bundle_root else None
        self.champion_target = str(champion_target).strip()
        if not self.champion_target:
            raise ValueError("champion_target must be non-empty")
        if self.mode == "champion" and (self.registry_root is None or self.bundle_root is None):
            raise ValueError("Champion mode requires registry_root and bundle_root")

    @classmethod
    def from_environment(
        cls,
        *,
        explicit_path: str | Path | None = None,
    ) -> ProjectionArtifactSource:
        # An explicitly supplied path is an intentional test/dev override and is never silently
        # promoted to champion mode by ambient environment variables.
        if explicit_path is not None:
            return cls(mode="path", path=explicit_path)

        mode = str(os.getenv("PSE_PROJECTION_SOURCE_MODE", "path")).strip().lower()
        if mode == "champion":
            return cls(
                mode="champion",
                registry_root=os.getenv("PSE_ARTIFACT_REGISTRY_ROOT", "artifacts/registry"),
                bundle_root=os.getenv("PSE_PRODUCTION_BUNDLE_ROOT"),
                champion_target=os.getenv(
                    "PSE_PROJECTION_CHAMPION_TARGET", DEFAULT_CHAMPION_TARGET
                ),
            )
        if mode != "path":
            raise ValueError(f"Unsupported PSE_PROJECTION_SOURCE_MODE={mode!r}")
        return cls(
            mode="path",
            path=os.getenv("PSE_PROJECTIONS_PATH", str(DEFAULT_PROJECTION_PATH)),
        )

    @staticmethod
    def _player_values_path(manifest: ArtifactBundleManifest, bundle_root: Path) -> Path:
        records = [record for record in manifest.files if record.role == "player_values"]
        if len(records) != 1:
            raise ValueError(
                "Production projection bundle must contain exactly one player_values artifact role"
            )
        return bundle_root / records[0].relative_path

    def _resolve_champion(self) -> tuple[ArtifactBundleManifest, Path]:
        assert self.registry_root is not None
        assert self.bundle_root is not None
        manifest = resolve_champion_bundle(
            self.registry_root,
            self.bundle_root,
            self.champion_target,
        )
        if manifest.authority != "production_approved":
            raise PermissionError(
                f"Champion bundle {manifest.bundle_id} has authority={manifest.authority!r}"
            )
        if not manifest.activation_eligible:
            raise PermissionError(
                f"Champion bundle {manifest.bundle_id} is not activation eligible"
            )
        if manifest.target != self.champion_target:
            raise ValueError(
                f"Champion target {manifest.target!r} != requested {self.champion_target!r}"
            )
        return manifest, self._player_values_path(manifest, self.bundle_root)

    def resolved_path(self) -> Path:
        if self.mode == "path":
            return self.path
        _manifest, path = self._resolve_champion()
        return path

    def load(self) -> ProjectionArtifactSnapshot:
        if self.mode == "path":
            candidate = self.path
            if not candidate.is_file():
                raise FileNotFoundError(candidate)
            frame = read_table(candidate)
            if frame.empty:
                raise ValueError("Projection artifact is empty")
            return ProjectionArtifactSnapshot(
                frame=frame,
                path=candidate,
                source_mode="path",
                authority="path_unverified",
                integrity_verified=False,
            )

        manifest, candidate = self._resolve_champion()
        if not candidate.is_file():
            # ``resolve_champion_bundle`` has already verified every manifest file. Keep this
            # additional role-specific assertion so a later refactor cannot return a phantom path.
            raise FileNotFoundError(candidate)
        frame = read_table(candidate)
        if frame.empty:
            raise ValueError("Verified champion projection artifact is empty")
        return ProjectionArtifactSnapshot(
            frame=frame,
            path=candidate,
            source_mode="champion",
            authority=manifest.authority,
            integrity_verified=True,
            target=manifest.target,
            bundle_id=manifest.bundle_id,
            model_id=manifest.model_id,
            code_sha=manifest.code_sha,
            source_cutoff_utc=manifest.source_cutoff_utc,
        )
