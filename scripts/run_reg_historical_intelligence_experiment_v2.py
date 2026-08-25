from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import run_rebaselined_historical_intelligence_experiment_v2 as runner

REGISTRY_PATH = Path("experiments/historical_official_availability_v2/registered_inputs.json")
_DEFAULT_NUMERICAL_ROOT = Path("data/raw/historical_numerical_baseline_v2")
_DEFAULT_INJURY_ROOT = Path("data/raw/historical_injury_archive_v2")
_DEFAULT_OUTPUT_ROOT = Path("artifacts/intelligence_ablations/historical_official_v2_reg")
_ORIGINAL_BUILD_WEEKLY_FEATURES = runner.build_weekly_features
_ORIGINAL_EXPERIMENT = runner.run_historical_intelligence_experiment


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_registry(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Registered experiment contract is not a JSON object: {path}")
    if payload.get("authority") != "research_evidence_only":
        raise ValueError("Registered experiment authority must remain research_evidence_only")
    return payload


def _file_name(record: dict[str, object]) -> str:
    source_url = str(record.get("source_url") or "")
    name = Path(urlparse(source_url).path).name
    if not name:
        raise ValueError(f"Registered source record has no file name: {record}")
    return name


def _verify_file(path: Path, record: dict[str, object], *, label: str) -> None:
    if not path.is_file():
        raise ValueError(f"Registered {label} source is missing: {path}")
    expected_bytes = int(record["bytes"])
    actual_bytes = path.stat().st_size
    if actual_bytes != expected_bytes:
        raise ValueError(
            f"Registered {label} byte mismatch for {path.name}: "
            f"expected {expected_bytes}, found {actual_bytes}"
        )
    expected_sha = str(record["sha256"])
    actual_sha = _sha256(path)
    if actual_sha != expected_sha:
        raise ValueError(
            f"Registered {label} SHA-256 mismatch for {path.name}: "
            f"expected {expected_sha}, found {actual_sha}"
        )


def _verify_numerical_sources(root: Path, registry: dict[str, object]) -> None:
    expected = registry.get("numerical_baseline")
    if not isinstance(expected, dict):
        raise ValueError("Registry is missing numerical_baseline")
    manifest_path = root / "NUMERICAL_BASELINE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Numerical baseline manifest is not a JSON object")

    for key in ("baseline_id", "identity_sha256", "schedule_commit"):
        if str(manifest.get(key) or "") != str(expected.get(key) or ""):
            raise ValueError(
                f"Registered numerical baseline {key} mismatch: "
                f"expected {expected.get(key)!r}, found {manifest.get(key)!r}"
            )

    expected_files = expected.get("files")
    manifest_files = manifest.get("files")
    if not isinstance(expected_files, list) or not isinstance(manifest_files, list):
        raise ValueError("Numerical baseline registry/manifest files must be lists")
    expected_by_name = {
        str(record["name"]): record for record in expected_files if isinstance(record, dict)
    }
    manifest_by_name = {
        str(record["name"]): record for record in manifest_files if isinstance(record, dict)
    }
    if set(manifest_by_name) != set(expected_by_name):
        raise ValueError(
            "Registered numerical source set mismatch: "
            f"expected {sorted(expected_by_name)}, found {sorted(manifest_by_name)}"
        )

    for name, record in expected_by_name.items():
        actual_record = manifest_by_name[name]
        for field in ("bytes", "sha256"):
            if str(actual_record.get(field)) != str(record.get(field)):
                raise ValueError(
                    f"Registered numerical manifest mismatch for {name}.{field}: "
                    f"expected {record.get(field)!r}, found {actual_record.get(field)!r}"
                )
        if record.get("source_commit") is not None and str(actual_record.get("source_commit")) != str(
            record.get("source_commit")
        ):
            raise ValueError(f"Registered numerical source commit mismatch for {name}")
        _verify_file(root / _file_name(record), record, label="numerical")

    print(f"NUMERICAL_BASELINE_IDENTITY_VERIFIED={expected['identity_sha256']}")


def _verify_injury_sources(root: Path, registry: dict[str, object]) -> None:
    expected = registry.get("injury_archive")
    if not isinstance(expected, dict):
        raise ValueError("Registry is missing injury_archive")
    expected_files = expected.get("files")
    if not isinstance(expected_files, list):
        raise ValueError("Registered injury files must be a list")

    manifest_path = root / "SOURCE_MANIFEST.csv"
    manifest = pd.read_csv(manifest_path)
    required = {"name", "bytes", "sha256", "status"}
    missing = required - set(manifest.columns)
    if missing:
        raise ValueError(f"Injury source manifest is missing columns: {sorted(missing)}")
    available = manifest.loc[manifest["status"].astype(str).str.startswith("available")].copy()
    manifest_by_name = {
        str(row["name"]): row for row in available.to_dict(orient="records")
    }
    expected_by_name = {
        str(record["name"]): record for record in expected_files if isinstance(record, dict)
    }
    if set(manifest_by_name) != set(expected_by_name):
        raise ValueError(
            "Registered injury source set mismatch: "
            f"expected {sorted(expected_by_name)}, found {sorted(manifest_by_name)}"
        )

    for name, record in expected_by_name.items():
        actual_record = manifest_by_name[name]
        if int(actual_record["bytes"]) != int(record["bytes"]):
            raise ValueError(f"Registered injury manifest byte mismatch for {name}")
        if str(actual_record["sha256"]) != str(record["sha256"]):
            raise ValueError(f"Registered injury manifest SHA-256 mismatch for {name}")
        _verify_file(root / _file_name(record), record, label="injury")

    print(f"INJURY_ARCHIVE_IDENTITY_VERIFIED={expected['identity_sha256']}")


def _verify_model_config(registry: dict[str, object]) -> Path:
    registered = registry.get("model_config")
    if not isinstance(registered, dict):
        raise ValueError("Registry is missing model_config")
    path = Path(str(registered.get("path") or ""))
    if not path.is_file():
        raise ValueError(f"Registered model config is missing: {path}")
    expected_sha = str(registered.get("sha256") or "")
    actual_sha = _sha256(path)
    if actual_sha != expected_sha:
        raise ValueError(
            "Registered model config SHA-256 mismatch: "
            f"expected {expected_sha}, found {actual_sha}"
        )
    print(f"MODEL_CONFIG_SHA256_VERIFIED={actual_sha}")
    return path


def _registered_runner_argv(
    registry: dict[str, object],
    *,
    numerical_root: Path,
    injury_root: Path,
    output_root: Path,
    config_path: Path,
) -> list[str]:
    contract = registry.get("evaluation_contract")
    if not isinstance(contract, dict):
        raise ValueError("Registry is missing evaluation_contract")
    if str(contract.get("primary_season_type")) != "REG":
        raise ValueError("Registered fantasy experiment must remain REG-only")
    if bool(contract.get("automatic_promotion")):
        raise ValueError("Registered experiment may not enable automatic promotion")
    if float(contract.get("prediction_cutoff_hours_before_kickoff", -1.0)) != 1.5:
        raise ValueError("Registered experiment cutoff must remain 1.5 hours before kickoff")

    seasons = contract.get("seasons")
    if not isinstance(seasons, list) or not seasons:
        raise ValueError("Registered evaluation seasons must be a non-empty list")
    target = str(contract.get("target") or "")
    if not target:
        raise ValueError("Registered evaluation target is missing")

    return [
        "run_rebaselined_historical_intelligence_experiment_v2.py",
        "--numerical-root",
        str(numerical_root),
        "--injury-root",
        str(injury_root),
        "--seasons",
        *(str(int(season)) for season in seasons),
        "--target",
        target,
        "--config",
        str(config_path),
        "--bootstrap-samples",
        str(int(contract["bootstrap_samples"])),
        "--minimum-source-coverage",
        str(float(contract["minimum_source_coverage"])),
        "--maximum-fdr-q",
        str(float(contract["maximum_fdr_q"])),
        "--minimum-consistency",
        str(float(contract["minimum_consistency"])),
        "--minimum-paired-rows",
        str(int(contract["minimum_paired_rows"])),
        "--minimum-seasons",
        str(int(contract["minimum_seasons"])),
        "--minimum-blocks",
        str(int(contract["minimum_blocks"])),
        "--minimum-position-rows",
        str(int(contract["minimum_position_rows"])),
        "--maximum-overall-coverage-gap-regression",
        str(float(contract["maximum_overall_coverage_gap_regression"])),
        "--maximum-position-coverage-gap-regression",
        str(float(contract["maximum_position_coverage_gap_regression"])),
        "--output-dir",
        str(output_root),
    ]


def _build_reg_only_features(*args: object, **kwargs: object) -> pd.DataFrame:
    """Build lagged history on all source rows, then restrict fit/evaluation to REG."""

    features = _ORIGINAL_BUILD_WEEKLY_FEATURES(*args, **kwargs)
    if "season_type" not in features.columns:
        raise ValueError("REG-only experiment requires season_type in the frozen player-stat source")
    season_type = features["season_type"].astype(str).str.upper().str.strip()
    regular = features.loc[season_type.eq("REG")].copy()
    if regular.empty:
        raise ValueError("REG-only experiment produced no regular-season feature rows")
    return regular.reset_index(drop=True)


def _experiment_with_prefit_coverage(
    replay,
    claims,
    source_coverage: pd.DataFrame,
    provenance,
    source_verification,
    **kwargs: object,
):
    """Persist observability before the model is allowed to reveal predictive lift."""

    context = replay.frame[["season", "week", "player_id", "position"]].drop_duplicates(
        ["season", "week", "player_id"]
    )
    audited = source_coverage.merge(
        context,
        on=["season", "week", "player_id"],
        how="left",
        validate="one_to_one",
    )
    overall = {
        "rows": int(len(audited)),
        "seasons": sorted(int(value) for value in audited["season"].dropna().unique()),
        "official_source_coverage": float(
            audited["official_availability_source_covered"].astype(bool).mean()
        ),
        "injury_source_coverage": float(
            audited["official_injury_report_source_covered"].astype(bool).mean()
        ),
        "evidence_prevalence": float(
            audited["official_availability_evidence_found"].astype(bool).mean()
        ),
        "missing_position_rows": int(audited["position"].isna().sum()),
    }
    by_slice = (
        audited.groupby(["season", "position"], dropna=False)
        .agg(
            rows=("player_id", "size"),
            official_source_coverage=("official_availability_source_covered", "mean"),
            injury_source_coverage=("official_injury_report_source_covered", "mean"),
            evidence_prevalence=("official_availability_evidence_found", "mean"),
        )
        .reset_index()
        .sort_values(["season", "position"])
    )

    variants = Path(str(kwargs.get("output_dir") or "artifacts/intelligence_ablations/v2/variants"))
    output_root = variants.parent
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "source_coverage_preflight.json").write_text(
        json.dumps(overall, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    by_slice.to_csv(output_root / "source_coverage_by_season_position.csv", index=False)
    print("SOURCE_COVERAGE_PREFLIGHT")
    print(json.dumps(overall, indent=2, sort_keys=True))
    print(by_slice.to_string(index=False))

    return _ORIGINAL_EXPERIMENT(
        replay,
        claims,
        source_coverage,
        provenance,
        source_verification,
        **kwargs,
    )


def _annotate_manifest(output_root: Path, registry_path: Path, registry: dict[str, object]) -> None:
    manifest_path = output_root / "run_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    numerical = registry["numerical_baseline"]
    injury = registry["injury_archive"]
    model_config = registry["model_config"]
    payload["registered_contract"] = {
        "path": registry_path.as_posix(),
        "sha256": _sha256(registry_path),
        "numerical_baseline_identity_sha256": numerical["identity_sha256"],
        "injury_archive_identity_sha256": injury["identity_sha256"],
        "model_config_sha256": model_config["sha256"],
        "evaluation_contract": registry["evaluation_contract"],
    }
    payload["evaluation_scope"] = {
        "season_type": "REG",
        "primary_use_case": "fantasy_regular_season",
        "postseason_rows_in_fit_or_evaluation": False,
        "feature_history_context": (
            "Lagged features are calculated from the complete chronological frozen source before "
            "evaluation rows are restricted to REG. Chronologically prior postseason games may "
            "therefore inform a later regular-season player's lagged state without entering fit "
            "or evaluation as postseason targets."
        ),
    }
    payload["historical_injury_adapter"] = {
        "nflverse_long_form_practice_statuses_supported_in_core": True,
        "supported_values": [
            "Full Participation in Practice",
            "Limited Participation in Practice",
            "Did Not Participate in Practice",
        ],
    }
    payload["interpretation_boundary"] = (
        "Primary fantasy-relevant regular-season research experiment on the exact registered v2 "
        "numerical baseline, injury archive, model configuration, and statistical contract. The "
        "result may support manual activation review only if every preregistered statistical, "
        "consistency, negative-control, calibration, source-coverage, and evidence-tier gate passes. "
        "It never grants automatic production authority."
    )
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the registered REG-only historical official-availability experiment. Data bytes, "
            "model configuration, seasons, target, and statistical gates are loaded from the "
            "content-addressed registry and cannot be overridden from the command line."
        )
    )
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--numerical-root", type=Path, default=_DEFAULT_NUMERICAL_ROOT)
    parser.add_argument("--injury-root", type=Path, default=_DEFAULT_INJURY_ROOT)
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()

    registry = _load_registry(args.registry)
    _verify_numerical_sources(args.numerical_root, registry)
    _verify_injury_sources(args.injury_root, registry)
    config_path = _verify_model_config(registry)

    runner.build_weekly_features = _build_reg_only_features
    runner.run_historical_intelligence_experiment = _experiment_with_prefit_coverage
    sys.argv = _registered_runner_argv(
        registry,
        numerical_root=args.numerical_root,
        injury_root=args.injury_root,
        output_root=args.output_dir,
        config_path=config_path,
    )
    runner.main()
    _annotate_manifest(args.output_dir, args.registry, registry)


if __name__ == "__main__":
    main()
