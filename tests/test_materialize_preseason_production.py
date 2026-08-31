from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from player_state_engine.learning.artifact_registry import (
    ArtifactIntegrityError,
    build_artifact_bundle,
    load_artifact_bundle_manifest,
    load_champion_pointer,
)
from scripts.materialize_preseason_production import REQUIRED_ROLES, TARGET, materialize_release


def _write_workflow_artifact(tmp_path: Path, *, tamper: bool = False) -> tuple[Path, str]:
    bundle_root = tmp_path / "candidate"
    bundle_root.mkdir()
    files: dict[str, Path] = {}
    for role in sorted(REQUIRED_ROLES):
        suffix = ".csv" if role == "player_values" else ".bin"
        path = bundle_root / f"{role}{suffix}"
        path.write_bytes(f"{role}\n".encode())
        files[role] = path

    challenger = build_artifact_bundle(
        bundle_root,
        files,
        artifact_type="preseason_multicontract_player_values_candidate",
        authority="challenger",
        activation_eligible=False,
        model_id="preseason_direct_league_score_v017",
        target=TARGET,
        code_sha="abc123",
        config_sha256="config123",
        source_cutoff_utc="2026-08-31T17:39:45+00:00",
        metadata={"season": 2026, "automatic_promotion": False},
    )
    if tamper:
        files["player_values"].write_text("tampered\n", encoding="utf-8")

    report = {
        "blocking_reasons": ["PROJECTION_BUNDLE_NOT_PRODUCTION_APPROVED"],
        "promotion_rehearsal_eligible": True,
        "rehearsal_status": "PROVISIONAL",
        "provisional_reasons": ["KNOWN_LIMITATION"],
        "leagues": [
            {
                "league": "8_team_ppr_2qb_expanded",
                "scoring_contract_id": "ppr",
                "core_readiness": {"ready": True},
            },
            {
                "league": "12_team_half_ppr_median",
                "scoring_contract_id": "half",
                "core_readiness": {"ready": True},
            },
            {
                "league": "12_team_half_ppr_median_2qb",
                "scoring_contract_id": "half",
                "core_readiness": {"ready": True},
            },
        ],
    }

    archive_path = tmp_path / "candidate.zip"
    prefix = "home/runner/work/nfl-player-state-engine/nfl-player-state-engine"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            f"{prefix}/artifacts/registry/bundles/{challenger.bundle_id}.json",
            challenger.model_dump_json(indent=2),
        )
        archive.writestr(
            f"{prefix}/artifacts/release_reports/preseason_2026_multicontract_rehearsal.json",
            json.dumps(report),
        )
        for record in challenger.files:
            archive.write(
                bundle_root / record.relative_path,
                f"{prefix}/artifacts/preseason_2026_multicontract_candidate/{record.relative_path}",
            )
        archive.writestr(f"{prefix}/tmp/nfl_hub/current.json", json.dumps({"status": "ok"}))
        archive.writestr(
            f"{prefix}/tmp/special_teams_market.json",
            json.dumps({"supported_positions": ["DST", "K"]}),
        )
    return archive_path, challenger.bundle_id


def test_materialize_release_promotes_exact_challenger_and_is_idempotent(tmp_path: Path) -> None:
    archive_path, challenger_id = _write_workflow_artifact(tmp_path)
    bundle_root = tmp_path / "production"
    registry_root = tmp_path / "registry"
    hub_path = tmp_path / "data/nfl_hub/current.json"
    special_path = tmp_path / "data/special_teams/current.json"
    activation_path = tmp_path / "activation.json"

    first = materialize_release(
        archive_path,
        approve_bundle_id=challenger_id,
        approved_by="release-owner",
        bundle_root=bundle_root,
        registry_root=registry_root,
        nfl_hub_path=hub_path,
        special_teams_path=special_path,
        activation_report_path=activation_path,
    )

    assert first["status"] == "ACTIVATED"
    assert first["challenger_bundle_id"] == challenger_id
    assert first["authority"] == "production_approved"
    assert first["activation_eligible"] is True
    assert first["production_bundle_id"] != challenger_id
    assert hub_path.is_file()
    assert special_path.is_file()
    assert activation_path.is_file()

    pointer = load_champion_pointer(registry_root)
    record = pointer.champions[TARGET]
    assert record.bundle_id == first["production_bundle_id"]
    production = load_artifact_bundle_manifest(registry_root, record.bundle_id)
    approval = production.metadata["manual_production_approval"]
    assert approval["source_challenger_bundle_id"] == challenger_id
    assert approval["approved_by"] == "release-owner"

    second = materialize_release(
        archive_path,
        approve_bundle_id=challenger_id,
        approved_by="release-owner",
        bundle_root=bundle_root,
        registry_root=registry_root,
        nfl_hub_path=hub_path,
        special_teams_path=special_path,
        activation_report_path=activation_path,
    )
    assert second["production_bundle_id"] == first["production_bundle_id"]


def test_materialize_release_rejects_tampered_candidate_bytes(tmp_path: Path) -> None:
    archive_path, challenger_id = _write_workflow_artifact(tmp_path, tamper=True)

    with pytest.raises(ArtifactIntegrityError, match="failed integrity checks"):
        materialize_release(
            archive_path,
            approve_bundle_id=challenger_id,
            approved_by="release-owner",
            bundle_root=tmp_path / "production",
            registry_root=tmp_path / "registry",
            nfl_hub_path=tmp_path / "data/nfl_hub/current.json",
            special_teams_path=tmp_path / "data/special_teams/current.json",
            activation_report_path=tmp_path / "activation.json",
        )
