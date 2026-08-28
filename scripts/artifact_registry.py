from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.learning.artifact_registry import (
    ArtifactBundleManifest,
    build_artifact_bundle,
    load_artifact_bundle_manifest,
    promote_artifact_bundle,
    resolve_champion_bundle,
    save_artifact_bundle_manifest,
    verify_artifact_bundle,
)


def _file_map(values: list[str]) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--file must use role=path syntax: {value!r}")
        role, raw_path = value.split("=", 1)
        role = role.strip()
        if not role or not raw_path.strip():
            raise ValueError(f"--file must use non-empty role=path syntax: {value!r}")
        if role in files:
            raise ValueError(f"Duplicate artifact role: {role}")
        files[role] = Path(raw_path)
    return files


def _metadata(values: list[str]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--metadata must use key=value syntax: {value!r}")
        key, item = value.split("=", 1)
        if not key.strip():
            raise ValueError("Metadata keys must be non-empty.")
        payload[key.strip()] = item
    return payload


def _cmd_register(args: argparse.Namespace) -> None:
    manifest = build_artifact_bundle(
        args.bundle_root,
        _file_map(args.file),
        artifact_type=args.artifact_type,
        authority=args.authority,
        activation_eligible=args.activation_eligible,
        model_id=args.model_id,
        target=args.target,
        code_sha=args.code_sha,
        config_sha256=args.config_sha256,
        source_cutoff_utc=args.source_cutoff_utc,
        metadata=_metadata(args.metadata),
    )
    path = save_artifact_bundle_manifest(manifest, args.registry_root)
    print(
        json.dumps(
            {
                "bundle_id": manifest.bundle_id,
                "manifest_path": str(path),
                "authority": manifest.authority,
                "activation_eligible": manifest.activation_eligible,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _cmd_verify(args: argparse.Namespace) -> None:
    manifest = load_artifact_bundle_manifest(args.registry_root, args.bundle_id)
    health = verify_artifact_bundle(manifest, args.bundle_root)
    print(json.dumps(health, indent=2, sort_keys=True))
    if not health["integrity_verified"]:
        raise SystemExit(2)


def _cmd_promote(args: argparse.Namespace) -> None:
    pointer = promote_artifact_bundle(
        args.registry_root,
        args.bundle_root,
        target=args.target,
        bundle_id=args.bundle_id,
        approved_by=args.approved_by,
        note=args.note,
    )
    print(pointer.model_dump_json(indent=2))


def _cmd_resolve(args: argparse.Namespace) -> None:
    manifest: ArtifactBundleManifest = resolve_champion_bundle(
        args.registry_root,
        args.bundle_root,
        args.target,
    )
    print(manifest.model_dump_json(indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Immutable production artifact registry operator.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register", help="Hash and register an immutable bundle.")
    register.add_argument("--bundle-root", required=True)
    register.add_argument("--registry-root", default="artifacts/registry")
    register.add_argument("--artifact-type", required=True)
    register.add_argument(
        "--authority",
        choices=("research_only", "challenger", "production_approved"),
        required=True,
    )
    register.add_argument("--activation-eligible", action="store_true")
    register.add_argument("--model-id")
    register.add_argument("--target")
    register.add_argument("--code-sha")
    register.add_argument("--config-sha256")
    register.add_argument("--source-cutoff-utc")
    register.add_argument("--file", action="append", default=[], help="role=path")
    register.add_argument("--metadata", action="append", default=[], help="key=value")
    register.set_defaults(func=_cmd_register)

    verify = subparsers.add_parser("verify", help="Rehash every file in a registered bundle.")
    verify.add_argument("--bundle-root", required=True)
    verify.add_argument("--registry-root", default="artifacts/registry")
    verify.add_argument("--bundle-id", required=True)
    verify.set_defaults(func=_cmd_verify)

    promote = subparsers.add_parser("promote", help="Move a champion pointer after manual approval.")
    promote.add_argument("--bundle-root", required=True)
    promote.add_argument("--registry-root", default="artifacts/registry")
    promote.add_argument("--target", required=True)
    promote.add_argument("--bundle-id", required=True)
    promote.add_argument("--approved-by", required=True)
    promote.add_argument("--note")
    promote.set_defaults(func=_cmd_promote)

    resolve = subparsers.add_parser("resolve", help="Resolve and verify the current champion.")
    resolve.add_argument("--bundle-root", required=True)
    resolve.add_argument("--registry-root", default="artifacts/registry")
    resolve.add_argument("--target", required=True)
    resolve.set_defaults(func=_cmd_resolve)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    arguments.func(arguments)
