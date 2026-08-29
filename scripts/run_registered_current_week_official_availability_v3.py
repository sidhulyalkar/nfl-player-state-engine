from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import run_current_week_official_availability_v3 as exploratory
import run_reg_historical_intelligence_experiment_v2 as registered_v2

REGISTRY_PATH = Path("experiments/current_week_official_availability_v3/registered_inputs.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_registry(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("v3 registry must be a JSON object")
    if payload.get("authority") != "posthoc_exploratory_research_only":
        raise ValueError("v3 authority must remain posthoc_exploratory_research_only")
    if bool(payload.get("automatic_promotion")):
        raise ValueError("v3 may never enable automatic promotion")
    if bool(payload.get("eligible_for_activation_review")):
        raise ValueError("v3 may never self-authorize activation review")
    return payload


def _assert_static_contract(
    registry: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    source = registry.get("source_contract")
    evaluation = registry.get("evaluation_contract")
    formulations = registry.get("formulations")
    if (
        not isinstance(source, dict)
        or not isinstance(evaluation, dict)
        or not isinstance(formulations, dict)
    ):
        raise ValueError("v3 registry is missing source/evaluation/formulation contracts")

    expected_formulations = {
        name: list(columns) for name, columns in exploratory._FORMULATIONS.items()
    }
    if formulations != expected_formulations:
        raise ValueError("v3 formulation registry does not match executable formulation definitions")
    if (
        set(evaluation.get("unverified_final_context_removed", []))
        != exploratory._UNVERIFIED_FINAL_CONTEXT
    ):
        raise ValueError("v3 removed-context registry does not match executable context exclusions")
    if evaluation.get("season_type") != "REG":
        raise ValueError("v3 must remain REG-only")
    if list(evaluation.get("seasons", [])) != [2020, 2021, 2022, 2023, 2024]:
        raise ValueError("v3 seasons are fixed to 2020-2024")
    if evaluation.get("target") != "fantasy_points_ppr":
        raise ValueError("v3 target must remain fantasy_points_ppr")
    if float(evaluation.get("prediction_cutoff_hours_before_kickoff", -1)) != 1.5:
        raise ValueError("v3 cutoff must remain 1.5 hours before kickoff")

    fixed_contract: dict[str, float | int] = {
        "bootstrap_samples": 2000,
        "seed": 4203,
        "minimum_source_coverage": 0.8,
        "maximum_joint_fdr_q": 0.1,
        "minimum_consistency": 0.55,
        "minimum_paired_rows": 250,
        "minimum_seasons": 2,
        "minimum_blocks": 8,
        "minimum_position_rows": 50,
        "maximum_overall_coverage_gap_regression": 0.02,
        "maximum_position_coverage_gap_regression": 0.05,
    }
    for key, expected in fixed_contract.items():
        actual = evaluation.get(key)
        if isinstance(expected, int):
            matches = int(actual if actual is not None else -1) == expected
        else:
            matches = float(actual if actual is not None else -1.0) == expected
        if not matches:
            raise ValueError(
                f"v3 registered {key} drifted: expected {expected!r}, found {actual!r}"
            )
    return source, evaluation


def _verify_source_and_model_contract(
    registry: dict[str, object], numerical_root: Path, injury_root: Path
) -> None:
    source, _ = _assert_static_contract(registry)
    v2_registry_path = Path(str(source["v2_registry_path"]))
    v2_registry = registered_v2._load_registry(v2_registry_path)

    if (
        v2_registry["numerical_baseline"]["identity_sha256"]
        != source["numerical_baseline_identity_sha256"]
    ):
        raise ValueError("v3 numerical identity disagrees with the canonical v2 registry")
    if (
        v2_registry["injury_archive"]["identity_sha256"]
        != source["injury_archive_identity_sha256"]
    ):
        raise ValueError("v3 injury identity disagrees with the canonical v2 registry")
    if v2_registry["model_config"]["sha256"] != source["model_config_sha256"]:
        raise ValueError("v3 model config identity disagrees with the canonical v2 registry")
    if (
        v2_registry["numerical_baseline"]["schedule_commit"]
        != source["schedule_commit"]
    ):
        raise ValueError("v3 schedule commit disagrees with the canonical v2 registry")

    registered_v2._verify_numerical_sources(numerical_root, v2_registry)
    registered_v2._verify_injury_sources(injury_root, v2_registry)
    config_path = registered_v2._verify_model_config(v2_registry)
    if config_path.as_posix() != str(source["model_config_path"]):
        raise ValueError("v3 model-config path differs from the registered source contract")

    _, _, injury_verification = exploratory.source_runner._injury_archive(injury_root)
    expected_injury_identity = str(source["injury_archive_identity_sha256"])
    if not injury_verification.verified:
        raise ValueError(
            f"v3 injury archive failed canonical verification: {injury_verification.failures}"
        )
    if injury_verification.archive_identity_sha256 != expected_injury_identity:
        raise ValueError(
            "v3 canonical injury archive identity mismatch: "
            f"expected {expected_injury_identity}, "
            f"found {injury_verification.archive_identity_sha256}"
        )


def _registered_screen_blockers(
    row: dict[str, object], evaluation: dict[str, object]
) -> list[str]:
    blockers: list[str] = []
    if float(row["effect"]) <= 0.0:
        blockers.append("incremental_effect_not_positive")
    if float(row["ci_low"]) <= 0.0:
        blockers.append("incremental_effect_ci_not_positive")
    if float(row["exploratory_joint_fdr_q"]) > float(evaluation["maximum_joint_fdr_q"]):
        blockers.append("joint_fdr_q_above_threshold")
    for label in ("season", "position", "week"):
        if float(row[f"{label}_consistency"]) < float(evaluation["minimum_consistency"]):
            blockers.append(f"inconsistent_{label}_effect")
    if int(row["paired_rows"]) < int(evaluation["minimum_paired_rows"]):
        blockers.append("insufficient_paired_rows")
    if int(row["paired_seasons"]) < int(evaluation["minimum_seasons"]):
        blockers.append("insufficient_paired_seasons")
    if int(row["paired_blocks"]) < int(evaluation["minimum_blocks"]):
        blockers.append("insufficient_paired_blocks")
    if float(row["source_coverage"]) < float(evaluation["minimum_source_coverage"]):
        blockers.append("insufficient_source_coverage")
    if not bool(row["identity_control_passed"]):
        blockers.append("identity_negative_control_failed")
    if float(row["coverage_gap_regression"]) > float(
        evaluation["maximum_overall_coverage_gap_regression"]
    ):
        blockers.append("overall_calibration_regression")
    position_regression = row.get("max_supported_position_coverage_gap_regression")
    supported_positions = int(row.get("supported_position_slices") or 0)
    if supported_positions <= 0 or position_regression is None:
        blockers.append("position_calibration_unmeasured")
    elif float(position_regression) > float(
        evaluation["maximum_position_coverage_gap_regression"]
    ):
        blockers.append("position_calibration_regression")
    return blockers


def _annotate_manifest(
    output_dir: Path, registry_path: Path, registry: dict[str, object]
) -> None:
    manifest_path = output_dir / "run_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    evaluation = registry["evaluation_contract"]
    rows = payload.get("formulations")
    if not isinstance(rows, list) or len(rows) != len(exploratory._FORMULATIONS):
        raise ValueError("v3 result manifest does not contain every registered formulation")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("v3 formulation result must be a JSON object")
        blockers = _registered_screen_blockers(row, evaluation)
        row["registered_exploratory_screen_blockers"] = blockers
        row["registered_exploratory_screen_passed"] = not blockers
        row["eligible_for_activation_review"] = False
        row["activation_review_blockers"] = [
            "posthoc_formulation_requires_independent_confirmation"
        ]

    payload["registered_contract"] = {
        "path": registry_path.as_posix(),
        "sha256": _sha256(registry_path),
        "evaluation_contract": evaluation,
        "formulations": registry["formulations"],
        "source_contract": registry["source_contract"],
    }
    payload["authority"] = "posthoc_exploratory_research_only"
    payload["automatic_promotion"] = False
    payload["eligible_for_activation_review"] = False
    payload["confirmation_boundary"] = registry["confirmation_boundary"]
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the registered post-hoc current-week official-availability v3 exploration. "
            "Scientific parameters are loaded from the immutable registry and cannot be overridden."
        )
    )
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument(
        "--numerical-root",
        type=Path,
        default=Path("data/raw/historical_numerical_baseline_v2"),
    )
    parser.add_argument(
        "--injury-root",
        type=Path,
        default=Path("data/raw/historical_injury_archive_v2"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/intelligence_ablations/current_week_official_v3"),
    )
    args = parser.parse_args()

    registry = _load_registry(args.registry)
    _, evaluation = _assert_static_contract(registry)
    _verify_source_and_model_contract(registry, args.numerical_root, args.injury_root)

    sys.argv = [
        "run_current_week_official_availability_v3.py",
        "--numerical-root",
        str(args.numerical_root),
        "--injury-root",
        str(args.injury_root),
        "--output-dir",
        str(args.output_dir),
        "--bootstrap-samples",
        str(int(evaluation["bootstrap_samples"])),
        "--seed",
        str(int(evaluation["seed"])),
    ]
    exploratory.main()
    _annotate_manifest(args.output_dir, args.registry, registry)


if __name__ == "__main__":
    main()
