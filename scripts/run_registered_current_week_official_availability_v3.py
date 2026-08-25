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


def _assert_static_contract(registry: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    source = registry.get("source_contract")
    evaluation = registry.get("evaluation_contract")
    formulations = registry.get("formulations")
    if not isinstance(source, dict) or not isinstance(evaluation, dict) or not isinstance(formulations, dict):
        raise ValueError("v3 registry is missing source/evaluation/formulation contracts")

    expected_formulations = {name: list(columns) for name, columns in exploratory._FORMULATIONS.items()}
    if formulations != expected_formulations:
        raise ValueError("v3 formulation registry does not match executable formulation definitions")
    if set(evaluation.get("unverified_final_context_removed", [])) != exploratory._UNVERIFIED_FINAL_CONTEXT:
        raise ValueError("v3 removed-context registry does not match executable context exclusions")
    if evaluation.get("season_type") != "REG":
        raise ValueError("v3 must remain REG-only")
    if list(evaluation.get("seasons", [])) != [2020, 2021, 2022, 2023, 2024]:
        raise ValueError("v3 seasons are fixed to 2020-2024")
    if evaluation.get("target") != "fantasy_points_ppr":
        raise ValueError("v3 target must remain fantasy_points_ppr")
    if float(evaluation.get("prediction_cutoff_hours_before_kickoff", -1)) != 1.5:
        raise ValueError("v3 cutoff must remain 1.5 hours before kickoff")
    if int(evaluation.get("bootstrap_samples", 0)) != 2000:
        raise ValueError("v3 bootstrap count is fixed at 2000")
    if int(evaluation.get("seed", -1)) != 4203:
        raise ValueError("v3 seed is fixed at 4203")
    return source, evaluation


def _verify_source_and_model_contract(
    registry: dict[str, object], numerical_root: Path, injury_root: Path
) -> None:
    source, _ = _assert_static_contract(registry)
    v2_registry_path = Path(str(source["v2_registry_path"]))
    v2_registry = registered_v2._load_registry(v2_registry_path)

    if v2_registry["numerical_baseline"]["identity_sha256"] != source["numerical_baseline_identity_sha256"]:
        raise ValueError("v3 numerical identity disagrees with the canonical v2 registry")
    if v2_registry["injury_archive"]["identity_sha256"] != source["injury_archive_identity_sha256"]:
        raise ValueError("v3 injury identity disagrees with the canonical v2 registry")
    if v2_registry["model_config"]["sha256"] != source["model_config_sha256"]:
        raise ValueError("v3 model config identity disagrees with the canonical v2 registry")
    if v2_registry["numerical_baseline"]["schedule_commit"] != source["schedule_commit"]:
        raise ValueError("v3 schedule commit disagrees with the canonical v2 registry")

    registered_v2._verify_numerical_sources(numerical_root, v2_registry)
    registered_v2._verify_injury_sources(injury_root, v2_registry)
    config_path = registered_v2._verify_model_config(v2_registry)
    if config_path.as_posix() != str(source["model_config_path"]):
        raise ValueError("v3 model-config path differs from the registered source contract")

    _, _, injury_verification = exploratory.source_runner._injury_archive(injury_root)
    expected_injury_identity = str(source["injury_archive_identity_sha256"])
    if not injury_verification.verified:
        raise ValueError(f"v3 injury archive failed canonical verification: {injury_verification.failures}")
    if injury_verification.archive_identity_sha256 != expected_injury_identity:
        raise ValueError(
            "v3 canonical injury archive identity mismatch: "
            f"expected {expected_injury_identity}, found {injury_verification.archive_identity_sha256}"
        )


def _annotate_manifest(output_dir: Path, registry_path: Path, registry: dict[str, object]) -> None:
    manifest_path = output_dir / "run_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["registered_contract"] = {
        "path": registry_path.as_posix(),
        "sha256": _sha256(registry_path),
        "evaluation_contract": registry["evaluation_contract"],
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
