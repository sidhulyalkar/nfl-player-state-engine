from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))
import run_reg_historical_intelligence_experiment_v2 as registered  # noqa: E402


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _evaluation_contract() -> dict[str, object]:
    return {
        "primary_season_type": "REG",
        "target": "fantasy_points_ppr",
        "seasons": [2020, 2021, 2022, 2023, 2024],
        "prediction_cutoff_hours_before_kickoff": 1.5,
        "bootstrap_samples": 2000,
        "minimum_source_coverage": 0.8,
        "maximum_fdr_q": 0.1,
        "minimum_consistency": 0.55,
        "minimum_paired_rows": 250,
        "minimum_seasons": 2,
        "minimum_blocks": 8,
        "minimum_position_rows": 50,
        "maximum_overall_coverage_gap_regression": 0.02,
        "maximum_position_coverage_gap_regression": 0.05,
        "automatic_promotion": False,
    }


def test_registered_file_verification_rejects_byte_and_hash_drift(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    path.write_bytes(b"registered-bytes\n")
    record = {
        "bytes": path.stat().st_size,
        "sha256": registered._sha256(path),
    }

    registered._verify_file(path, record, label="test")

    path.write_bytes(b"changed-bytes\n")
    with pytest.raises(ValueError, match="byte mismatch|SHA-256 mismatch"):
        registered._verify_file(path, record, label="test")


def test_registered_model_config_rejects_content_drift(tmp_path: Path) -> None:
    config = tmp_path / "base.yaml"
    config.write_text("model:\n  random_seed: 42\n", encoding="utf-8")
    registry = {
        "model_config": {
            "path": config.as_posix(),
            "sha256": registered._sha256(config),
        }
    }

    assert registered._verify_model_config(registry) == config

    config.write_text("model:\n  random_seed: 43\n", encoding="utf-8")
    with pytest.raises(ValueError, match="model config SHA-256 mismatch"):
        registered._verify_model_config(registry)


def test_registered_numerical_sources_reject_raw_tamper(tmp_path: Path) -> None:
    stats = tmp_path / "stats_player_week_2020.csv"
    games = tmp_path / "games.csv"
    stats.write_bytes(b"player,week\np1,1\n")
    games.write_bytes(b"game_id\n2020_01_A_B\n")
    records = [
        {
            "name": "player_stats_2020",
            "bytes": stats.stat().st_size,
            "sha256": registered._sha256(stats),
            "source_url": "https://example.test/stats_player_week_2020.csv",
        },
        {
            "name": "schedules",
            "bytes": games.stat().st_size,
            "sha256": registered._sha256(games),
            "source_commit": "schedule-commit",
            "source_url": "https://example.test/games.csv",
        },
    ]
    manifest = {
        "baseline_id": "registered-baseline",
        "identity_sha256": "registered-identity",
        "schedule_commit": "schedule-commit",
        "files": [
            {**record, "path": (tmp_path / registered._file_name(record)).as_posix()}
            for record in records
        ],
    }
    (tmp_path / "NUMERICAL_BASELINE_MANIFEST.json").write_text(
        __import__("json").dumps(manifest), encoding="utf-8"
    )
    registry = {
        "numerical_baseline": {
            "baseline_id": "registered-baseline",
            "identity_sha256": "registered-identity",
            "schedule_commit": "schedule-commit",
            "files": records,
        }
    }

    registered._verify_numerical_sources(tmp_path, registry)

    games.write_bytes(b"game_id\ntampered\n")
    with pytest.raises(ValueError, match="numerical.*mismatch"):
        registered._verify_numerical_sources(tmp_path, registry)


def test_registered_injury_sources_reject_manifest_or_raw_tamper(tmp_path: Path) -> None:
    injury = tmp_path / "injuries_2020.csv"
    injury.write_bytes(b"season,week\n2020,1\n")
    record = {
        "name": "injuries_2020",
        "bytes": injury.stat().st_size,
        "sha256": registered._sha256(injury),
        "source_url": "https://example.test/injuries_2020.csv",
    }
    manifest = pd.DataFrame(
        [
            {
                "name": record["name"],
                "path": injury.as_posix(),
                "bytes": record["bytes"],
                "sha256": record["sha256"],
                "status": "available",
            }
        ]
    )
    manifest.to_csv(tmp_path / "SOURCE_MANIFEST.csv", index=False)
    registry = {
        "injury_archive": {
            "identity_sha256": "registered-injury-identity",
            "files": [record],
        }
    }

    registered._verify_injury_sources(tmp_path, registry)

    manifest.loc[0, "sha256"] = "0" * 64
    manifest.to_csv(tmp_path / "SOURCE_MANIFEST.csv", index=False)
    with pytest.raises(ValueError, match="injury manifest SHA-256 mismatch"):
        registered._verify_injury_sources(tmp_path, registry)

    manifest.loc[0, "sha256"] = record["sha256"]
    manifest.to_csv(tmp_path / "SOURCE_MANIFEST.csv", index=False)
    injury.write_bytes(b"season,week\n2020,2\n")
    with pytest.raises(ValueError, match="injury.*mismatch"):
        registered._verify_injury_sources(tmp_path, registry)


def test_runner_argv_is_derived_from_registered_contract() -> None:
    registry = {"evaluation_contract": _evaluation_contract()}
    argv = registered._registered_runner_argv(
        registry,
        numerical_root=Path("numerical"),
        injury_root=Path("injuries"),
        output_root=Path("output"),
        config_path=Path("configs/base.yaml"),
    )

    assert argv[argv.index("--target") + 1] == "fantasy_points_ppr"
    assert argv[argv.index("--bootstrap-samples") + 1] == "2000"
    assert argv[argv.index("--maximum-fdr-q") + 1] == "0.1"
    assert argv[argv.index("--minimum-consistency") + 1] == "0.55"
    assert argv[argv.index("--minimum-paired-rows") + 1] == "250"
    season_index = argv.index("--seasons") + 1
    assert argv[season_index : season_index + 5] == ["2020", "2021", "2022", "2023", "2024"]


def test_runner_contract_refuses_scope_or_promotion_drift() -> None:
    contract = _evaluation_contract()
    contract["primary_season_type"] = "POST"
    with pytest.raises(ValueError, match="REG-only"):
        registered._registered_runner_argv(
            {"evaluation_contract": contract},
            numerical_root=Path("numerical"),
            injury_root=Path("injuries"),
            output_root=Path("output"),
            config_path=Path("configs/base.yaml"),
        )

    contract = _evaluation_contract()
    contract["automatic_promotion"] = True
    with pytest.raises(ValueError, match="automatic promotion"):
        registered._registered_runner_argv(
            {"evaluation_contract": contract},
            numerical_root=Path("numerical"),
            injury_root=Path("injuries"),
            output_root=Path("output"),
            config_path=Path("configs/base.yaml"),
        )
