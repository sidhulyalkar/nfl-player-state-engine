from __future__ import annotations

import csv
from pathlib import Path

from player_state_engine.learning.artifact_registry import (
    build_artifact_bundle,
    promote_artifact_bundle,
    save_artifact_bundle_manifest,
)
from scripts.check_draft_checkout import (
    _production_projection_check,
    _projection_contract_check,
)

TARGET = "preseason_multicontract_player_values_2026"


def _write_projection(path: Path, *, rows_per_contract: int = 250) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "scoring_contract_id",
        "player_id",
        "league_season_points_q50",
        "league_scoring_exact",
        "decision_quantile_policy",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for contract, policy in (
            ("scoring-v1-ppr", "qualified_distribution"),
            ("scoring-v1-half", "q50_only"),
        ):
            for index in range(rows_per_contract):
                writer.writerow(
                    {
                        "scoring_contract_id": contract,
                        "player_id": f"p{index:03d}",
                        "league_season_points_q50": 100.0 + index,
                        "league_scoring_exact": "true",
                        "decision_quantile_policy": policy,
                    }
                )


def _promoted_champion(root: Path) -> tuple[Path, Path, Path]:
    bundle_root = root / "bundle"
    registry_root = root / "registry"
    values_path = bundle_root / "product_player_values.csv"
    _write_projection(values_path)
    manifest = build_artifact_bundle(
        bundle_root,
        {"player_values": values_path},
        artifact_type="preseason_multicontract_player_values_production",
        authority="production_approved",
        activation_eligible=True,
        model_id="preseason_direct_league_score_v017",
        target=TARGET,
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
    return bundle_root, registry_root, values_path


def test_projection_contract_preflight_accepts_current_multicontract_shape(tmp_path: Path) -> None:
    path = tmp_path / "product_player_values.csv"
    _write_projection(path)

    ok, detail = _projection_contract_check(path)

    assert ok is True
    assert "2 contracts" in detail
    assert "min_contract_rows=250" in detail
    assert "qualified_distribution" in detail
    assert "q50_only" in detail


def test_projection_contract_preflight_rejects_old_universal_shape(tmp_path: Path) -> None:
    path = tmp_path / "product_player_values.csv"
    path.write_text("player_id,season_points_q50\np1,123\n", encoding="utf-8")

    ok, detail = _projection_contract_check(path)

    assert ok is False
    assert "legacy/incomplete projection schema" in detail
    assert "scoring_contract_id" in detail


def test_projection_contract_preflight_rejects_duplicate_player_inside_contract(tmp_path: Path) -> None:
    path = tmp_path / "product_player_values.csv"
    _write_projection(path)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "scoring_contract_id",
                "player_id",
                "league_season_points_q50",
                "league_scoring_exact",
                "decision_quantile_policy",
            ],
        )
        writer.writerow(
            {
                "scoring_contract_id": "scoring-v1-ppr",
                "player_id": "p000",
                "league_season_points_q50": 999.0,
                "league_scoring_exact": "true",
                "decision_quantile_policy": "qualified_distribution",
            }
        )

    ok, detail = _projection_contract_check(path)

    assert ok is False
    assert "duplicate contract/player rows" in detail


def test_actual_draft_preflight_rejects_schema_valid_path_mode(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "product_player_values.csv"
    _write_projection(path)
    monkeypatch.setenv("PSE_PROJECTION_SOURCE_MODE", "path")
    monkeypatch.setenv("PSE_PROJECTIONS_PATH", str(path))

    ok, detail = _production_projection_check(tmp_path)

    assert ok is False
    assert "path_unverified" in detail
    assert "requires PSE_PROJECTION_SOURCE_MODE=champion" in detail


def test_actual_draft_preflight_accepts_verified_promoted_champion(
    tmp_path: Path, monkeypatch
) -> None:
    bundle_root, registry_root, _values_path = _promoted_champion(tmp_path)
    monkeypatch.setenv("PSE_PROJECTION_SOURCE_MODE", "champion")
    monkeypatch.setenv("PSE_ARTIFACT_REGISTRY_ROOT", str(registry_root))
    monkeypatch.setenv("PSE_PRODUCTION_BUNDLE_ROOT", str(bundle_root))
    monkeypatch.setenv("PSE_PROJECTION_CHAMPION_TARGET", TARGET)

    ok, detail = _production_projection_check(tmp_path)

    assert ok is True
    assert "verified champion bundle=" in detail
    assert f"target={TARGET}" in detail
    assert "2 contracts" in detail


def test_actual_draft_preflight_detects_champion_tampering(
    tmp_path: Path, monkeypatch
) -> None:
    bundle_root, registry_root, values_path = _promoted_champion(tmp_path)
    monkeypatch.setenv("PSE_PROJECTION_SOURCE_MODE", "champion")
    monkeypatch.setenv("PSE_ARTIFACT_REGISTRY_ROOT", str(registry_root))
    monkeypatch.setenv("PSE_PRODUCTION_BUNDLE_ROOT", str(bundle_root))
    monkeypatch.setenv("PSE_PROJECTION_CHAMPION_TARGET", TARGET)
    values_path.write_text("player_id\nTAMPERED\n", encoding="utf-8")

    ok, detail = _production_projection_check(tmp_path)

    assert ok is False
    assert "verified champion unavailable" in detail
    assert "failed integrity checks" in detail
