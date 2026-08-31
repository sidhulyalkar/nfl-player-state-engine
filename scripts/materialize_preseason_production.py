from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from player_state_engine.learning.approval_derivation import derive_production_approved_bundle
from player_state_engine.learning.artifact_registry import (
    ArtifactBundleManifest,
    ArtifactIntegrityError,
    load_artifact_bundle_manifest,
    load_champion_pointer,
    promote_artifact_bundle,
    require_valid_bundle,
    save_artifact_bundle_manifest,
)

TARGET = "preseason_multicontract_player_values_2026"
EXPECTED_LEAGUES = {
    "8_team_ppr_2qb_expanded",
    "12_team_half_ppr_median",
    "12_team_half_ppr_median_2qb",
}
REQUIRED_ROLES = {
    "calibrator_8_team_ppr_2qb_expanded",
    "contract_metadata",
    "current_preseason_features",
    "direct_score_evidence",
    "model_12_team_half_ppr_median",
    "model_8_team_ppr_2qb_expanded",
    "player_values",
    "qualification_evidence",
    "uncertainty_evidence",
}
ALLOWED_PREAPPROVAL_BLOCKERS = {"PROJECTION_BUNDLE_NOT_PRODUCTION_APPROVED"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ArtifactIntegrityError(f"Unsafe artifact relative path: {raw!r}")
    return path


def _one_member_by_suffix(archive: zipfile.ZipFile, suffix: str) -> str:
    normalized = suffix.lstrip("/")
    matches = [name for name in archive.namelist() if name.rstrip("/").endswith(normalized)]
    if len(matches) != 1:
        raise ArtifactIntegrityError(
            f"Expected exactly one archive member ending in {normalized!r}; found {len(matches)}"
        )
    return matches[0]


def _json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    name = _one_member_by_suffix(archive, suffix)
    try:
        payload = json.loads(archive.read(name).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactIntegrityError(f"Invalid JSON in workflow artifact member {name}") from exc
    if not isinstance(payload, dict):
        raise ArtifactIntegrityError(f"Expected JSON object in workflow artifact member {name}")
    return payload


def _validate_release_report(report: dict[str, Any]) -> None:
    if report.get("promotion_rehearsal_eligible") is not True:
        raise PermissionError("Release rehearsal is not promotion eligible.")

    blockers = {str(value) for value in report.get("blocking_reasons", [])}
    unexpected = blockers - ALLOWED_PREAPPROVAL_BLOCKERS
    if unexpected:
        raise PermissionError(f"Unexpected hard release blockers: {sorted(unexpected)}")

    leagues = report.get("leagues")
    if not isinstance(leagues, list):
        raise ArtifactIntegrityError("Release report does not contain league qualification rows.")
    by_name = {
        str(row.get("league")): row
        for row in leagues
        if isinstance(row, dict) and row.get("league")
    }
    if set(by_name) != EXPECTED_LEAGUES:
        raise ArtifactIntegrityError(
            f"Release report league set mismatch: expected {sorted(EXPECTED_LEAGUES)}, "
            f"found {sorted(by_name)}"
        )
    for league_name, row in by_name.items():
        core = row.get("core_readiness")
        if not isinstance(core, dict) or core.get("ready") is not True:
            raise PermissionError(f"Core draft readiness is not green for {league_name}.")

    one_qb = by_name["12_team_half_ppr_median"].get("scoring_contract_id")
    two_qb = by_name["12_team_half_ppr_median_2qb"].get("scoring_contract_id")
    if not one_qb or one_qb != two_qb:
        raise ArtifactIntegrityError(
            "The two half-PPR roster constructions must share one scoring-model contract."
        )


def _validate_challenger(
    manifest: ArtifactBundleManifest,
    *,
    expected_bundle_id: str,
) -> None:
    if manifest.bundle_id != expected_bundle_id:
        raise ArtifactIntegrityError(
            f"Challenger bundle mismatch: expected {expected_bundle_id}, found {manifest.bundle_id}"
        )
    if manifest.authority != "challenger" or manifest.activation_eligible:
        raise PermissionError("Release input must be a non-activation-eligible challenger.")
    if manifest.target != TARGET:
        raise ArtifactIntegrityError(
            f"Release target mismatch: expected {TARGET!r}, found {manifest.target!r}"
        )
    roles = {record.role for record in manifest.files}
    missing = REQUIRED_ROLES - roles
    if missing:
        raise ArtifactIntegrityError(f"Challenger is missing required roles: {sorted(missing)}")


def _copy_member(archive: zipfile.ZipFile, member: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member) as source, destination.open("wb") as output:
        shutil.copyfileobj(source, output)


def _existing_approved_champion(
    registry_root: Path,
    bundle_root: Path,
    *,
    challenger_bundle_id: str,
) -> ArtifactBundleManifest | None:
    pointer = load_champion_pointer(registry_root)
    record = pointer.champions.get(TARGET)
    if record is None:
        return None
    manifest = load_artifact_bundle_manifest(registry_root, record.bundle_id)
    require_valid_bundle(manifest, bundle_root)
    approval = manifest.metadata.get("manual_production_approval")
    if not isinstance(approval, dict):
        return None
    if approval.get("source_challenger_bundle_id") != challenger_bundle_id:
        return None
    if manifest.authority != "production_approved" or not manifest.activation_eligible:
        return None
    return manifest


def materialize_release(
    artifact_zip: str | Path,
    *,
    approve_bundle_id: str,
    approved_by: str,
    bundle_root: str | Path = "artifacts/production/preseason_2026",
    registry_root: str | Path = "artifacts/registry",
    nfl_hub_path: str | Path = "data/product/nfl_hub/current.json",
    special_teams_path: str | Path = "data/product/special_teams_market/current.json",
    activation_report_path: str | Path = "artifacts/release_reports/preseason_2026_activation.json",
    note: str = "Reviewed 2026 three-league release rehearsal",
    replace_existing_champion: bool = False,
) -> dict[str, Any]:
    """Materialize, approve, and promote one exact reviewed preseason workflow artifact.

    ``approve_bundle_id`` is intentionally required and must match the challenger's content-addressed
    identity. Supplying it is the operator's explicit approval of that exact challenger.
    """

    artifact_path = Path(artifact_zip)
    if not artifact_path.is_file():
        raise FileNotFoundError(artifact_path)
    approver = approved_by.strip()
    if not approver:
        raise ValueError("approved_by is required; automatic approval is prohibited.")
    expected_bundle_id = approve_bundle_id.strip()
    if not expected_bundle_id:
        raise ValueError("approve_bundle_id is required.")

    output_bundle_root = Path(bundle_root)
    output_registry_root = Path(registry_root)
    output_hub_path = Path(nfl_hub_path)
    output_special_teams_path = Path(special_teams_path)
    output_activation_report = Path(activation_report_path)

    with zipfile.ZipFile(artifact_path) as archive:
        report = _json_member(
            archive,
            "artifacts/release_reports/preseason_2026_multicontract_rehearsal.json",
        )
        _validate_release_report(report)

        manifest_payload = _json_member(
            archive,
            f"artifacts/registry/bundles/{expected_bundle_id}.json",
        )
        challenger = ArtifactBundleManifest.model_validate(manifest_payload)
        _validate_challenger(challenger, expected_bundle_id=expected_bundle_id)

        output_bundle_root.mkdir(parents=True, exist_ok=True)
        for record in challenger.files:
            relative = _safe_relative_path(record.relative_path)
            archive_member = _one_member_by_suffix(
                archive,
                f"artifacts/preseason_2026_multicontract_candidate/{relative.as_posix()}",
            )
            _copy_member(archive, archive_member, output_bundle_root / Path(*relative.parts))

        save_artifact_bundle_manifest(challenger, output_registry_root)
        require_valid_bundle(challenger, output_bundle_root)

        existing = _existing_approved_champion(
            output_registry_root,
            output_bundle_root,
            challenger_bundle_id=challenger.bundle_id,
        )
        if existing is not None:
            production = existing
        else:
            pointer = load_champion_pointer(output_registry_root)
            current = pointer.champions.get(TARGET)
            if current is not None and not replace_existing_champion:
                raise PermissionError(
                    f"Champion target {TARGET!r} already points to {current.bundle_id}; "
                    "pass --replace-existing-champion only after reviewing that authority change."
                )
            production = derive_production_approved_bundle(
                output_registry_root,
                output_bundle_root,
                challenger_bundle_id=challenger.bundle_id,
                approved_by=approver,
                approval_note=note,
            )
            promote_artifact_bundle(
                output_registry_root,
                output_bundle_root,
                target=TARGET,
                bundle_id=production.bundle_id,
                approved_by=approver,
                note="Activate reviewed 2026 draft champion",
            )

        hub_member = _one_member_by_suffix(archive, "tmp/nfl_hub/current.json")
        special_teams_member = _one_member_by_suffix(archive, "tmp/special_teams_market.json")
        _copy_member(archive, hub_member, output_hub_path)
        _copy_member(archive, special_teams_member, output_special_teams_path)

    require_valid_bundle(production, output_bundle_root)
    approval = production.metadata.get("manual_production_approval") or {}
    result = {
        "status": "ACTIVATED",
        "challenger_bundle_id": challenger.bundle_id,
        "production_bundle_id": production.bundle_id,
        "target": production.target,
        "authority": production.authority,
        "activation_eligible": production.activation_eligible,
        "approved_by": approval.get("approved_by", approver),
        "approved_at_utc": approval.get("approved_at_utc"),
        "source_code_sha": production.code_sha,
        "source_cutoff_utc": production.source_cutoff_utc,
        "workflow_artifact_sha256": _sha256_file(artifact_path),
        "bundle_root": str(output_bundle_root),
        "registry_root": str(output_registry_root),
        "nfl_hub_path": str(output_hub_path),
        "special_teams_path": str(output_special_teams_path),
        "rehearsal_status": report.get("rehearsal_status"),
        "provisional_reasons": report.get("provisional_reasons", []),
        "runtime_environment": {
            "PSE_PROJECTION_SOURCE_MODE": "champion",
            "PSE_ARTIFACT_REGISTRY_ROOT": str(output_registry_root),
            "PSE_PRODUCTION_BUNDLE_ROOT": str(output_bundle_root),
            "PSE_PROJECTION_CHAMPION_TARGET": TARGET,
        },
    }
    output_activation_report.parent.mkdir(parents=True, exist_ok=True)
    output_activation_report.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install one exact reviewed 2026 preseason workflow artifact, derive production "
            "authority over unchanged bytes, and promote it as the verified local champion."
        )
    )
    parser.add_argument("artifact_zip", type=Path)
    parser.add_argument("--approve-bundle-id", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument(
        "--bundle-root",
        type=Path,
        default=Path("artifacts/production/preseason_2026"),
    )
    parser.add_argument(
        "--registry-root",
        type=Path,
        default=Path("artifacts/registry"),
    )
    parser.add_argument("--note", default="Reviewed 2026 three-league release rehearsal")
    parser.add_argument(
        "--replace-existing-champion",
        action="store_true",
        help="Permit replacing an already promoted champion after explicit review.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = materialize_release(
        args.artifact_zip,
        approve_bundle_id=args.approve_bundle_id,
        approved_by=args.approved_by,
        bundle_root=args.bundle_root,
        registry_root=args.registry_root,
        note=args.note,
        replace_existing_champion=args.replace_existing_champion,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
