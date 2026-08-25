from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from player_state_engine.config import load_config
from player_state_engine.data.historical import read_historical_table
from player_state_engine.data.io import read_table, write_table
from player_state_engine.evaluation.historical_intelligence_experiment import (
    build_historical_feature_replay,
    run_historical_intelligence_experiment,
    sha256_file,
    verify_frozen_benchmark_sources,
)
from player_state_engine.evaluation.intelligence_provenance import IntelligenceEvidenceProvenance
from player_state_engine.intelligence.structured import StructuredClaimLedger


def _git_sha() -> str | None:
    value = os.environ.get("GITHUB_SHA")
    if value:
        return value
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _tree_digest(root: Path) -> str:
    if not root.exists():
        raise FileNotFoundError(f"Artifact tree unavailable: {root}")
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise ValueError(f"Artifact tree contains no files: {root}")
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(sha256_file(path).encode("ascii"))
    return digest.hexdigest()


def _json_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _input_record(path: Path) -> dict[str, object]:
    return {
        "path": path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen historical structured-intelligence experiment using current model code, "
            "content-addressed benchmark inputs, the immutable official-evidence ledger, and the "
            "separate source-coverage artifact. This command never enables an intelligence family."
        )
    )
    parser.add_argument(
        "--benchmark-root",
        type=Path,
        default=Path("artifacts/reports/benchmark_real"),
    )
    parser.add_argument(
        "--benchmark-source-dir",
        type=Path,
        default=Path("data/raw/frozen_benchmark_sources"),
        help=(
            "Directory containing the raw player-stat and schedule files named by the frozen "
            "benchmark DATA_MANIFEST.json."
        ),
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=Path("artifacts/intelligence_corpus/historical_official"),
        help="Output root created by scripts/build_historical_intelligence_corpus.py.",
    )
    parser.add_argument("--seasons", nargs="+", type=int, default=[2021, 2022, 2023, 2024])
    parser.add_argument("--target", default="fantasy_points_ppr")
    parser.add_argument("--config", type=Path, default=Path("configs/base.yaml"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/intelligence_ablations/historical_official"),
    )
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--minimum-source-coverage", type=float, default=0.80)
    parser.add_argument("--maximum-fdr-q", type=float, default=0.10)
    parser.add_argument("--minimum-consistency", type=float, default=0.55)
    parser.add_argument("--minimum-paired-rows", type=int, default=250)
    parser.add_argument("--minimum-seasons", type=int, default=2)
    parser.add_argument("--minimum-blocks", type=int, default=8)
    parser.add_argument("--minimum-position-rows", type=int, default=50)
    parser.add_argument("--maximum-overall-coverage-gap-regression", type=float, default=0.02)
    parser.add_argument("--maximum-position-coverage-gap-regression", type=float, default=0.05)
    parser.add_argument(
        "--allow-unverified-benchmark-sources",
        action="store_true",
        help=(
            "Permit a research-only run when benchmark source hashes drift. Activation-review "
            "eligibility is forcibly disabled for every family in such a run. Missing source "
            "files are never bypassed."
        ),
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify frozen benchmark source bytes and exit before model fitting.",
    )
    args = parser.parse_args()

    seasons = tuple(sorted(set(int(season) for season in args.seasons)))
    if not seasons:
        raise ValueError("--seasons cannot be empty")
    if args.bootstrap_samples <= 0:
        raise ValueError("--bootstrap-samples must be positive")

    benchmark_manifest = args.benchmark_root / "DATA_MANIFEST.json"
    if not benchmark_manifest.is_file():
        raise FileNotFoundError(f"Frozen benchmark manifest unavailable: {benchmark_manifest}")
    verification = verify_frozen_benchmark_sources(
        benchmark_manifest,
        args.benchmark_source_dir,
        seasons=seasons,
    )
    verification_payload = {
        "verified": verification.verified,
        "source_identity_sha256": verification.source_identity_sha256,
        "failures": list(verification.failures),
        "files": list(verification.files),
    }
    if args.verify_only:
        print(json.dumps(verification_payload, indent=2, sort_keys=True))
        return

    missing_paths = [
        path for _, raw_path in verification.paths if not (path := Path(raw_path)).is_file()
    ]
    if missing_paths:
        raise FileNotFoundError(
            "Frozen benchmark source files are missing: "
            + ", ".join(path.as_posix() for path in missing_paths)
        )
    if not verification.verified and not args.allow_unverified_benchmark_sources:
        raise ValueError(
            "Frozen benchmark source verification failed: "
            + "; ".join(verification.failures)
            + ". Refusing to run a nominally frozen experiment on drifted source bytes."
        )

    coverage_path = args.corpus_root / "source_coverage.parquet"
    provenance_path = args.corpus_root / "evidence_provenance.json"
    ledger_root = args.corpus_root / "ledger"
    for path in (coverage_path, provenance_path):
        if not path.is_file():
            raise FileNotFoundError(
                f"Historical intelligence corpus artifact unavailable: {path}. "
                "Run scripts/build_historical_intelligence_corpus.py first."
            )
    if not ledger_root.is_dir():
        raise FileNotFoundError(
            f"Historical structured-claim ledger unavailable: {ledger_root}. "
            "Run scripts/build_historical_intelligence_corpus.py first."
        )

    player_paths = [
        Path(raw_path)
        for name, raw_path in verification.paths
        if name.startswith("player_stats_")
    ]
    if not player_paths:
        raise ValueError("Frozen source verification resolved no player-stat files")
    player_stats = pd.concat(
        [read_historical_table(path) for path in player_paths],
        ignore_index=True,
        sort=False,
    )
    schedules = read_historical_table(verification.path_for("schedules"))
    source_coverage = read_table(coverage_path)
    config = load_config(args.config)

    replay = build_historical_feature_replay(
        player_stats,
        schedules,
        source_coverage,
        benchmark_root=args.benchmark_root,
        seasons=seasons,
        target=args.target,
        config=config,
    )

    ledger = StructuredClaimLedger(ledger_root)
    ledger_health = ledger.health()
    if not ledger_health["integrity_verified"]:
        raise ValueError(
            "Historical structured-claim ledger failed integrity verification: "
            + "; ".join(str(item) for item in ledger_health["integrity_failures"])
        )
    claims = ledger.claims()
    provenance = IntelligenceEvidenceProvenance.load(provenance_path)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    experiment = run_historical_intelligence_experiment(
        replay,
        claims,
        source_coverage,
        provenance,
        verification,
        config=config,
        target=args.target,
        output_dir=args.output_dir / "variants",
        bootstrap_samples=args.bootstrap_samples,
        minimum_source_coverage=args.minimum_source_coverage,
        maximum_fdr_q=args.maximum_fdr_q,
        minimum_consistency=args.minimum_consistency,
        minimum_paired_rows=args.minimum_paired_rows,
        minimum_seasons=args.minimum_seasons,
        minimum_blocks=args.minimum_blocks,
        minimum_position_rows=args.minimum_position_rows,
        maximum_overall_coverage_gap_regression=args.maximum_overall_coverage_gap_regression,
        maximum_position_coverage_gap_regression=args.maximum_position_coverage_gap_regression,
    )

    replay_path = Path(write_table(replay.frame, args.output_dir / "replay_features.parquet"))
    point_in_time_path = Path(
        write_table(experiment.frame, args.output_dir / "point_in_time_features.parquet")
    )
    evidence_path = Path(
        write_table(experiment.evidence, args.output_dir / "incremental_evidence.csv")
    )
    replay_audit_path = args.output_dir / "replay_audit.json"
    experiment_audit_path = args.output_dir / "experiment_audit.json"
    source_verification_path = args.output_dir / "benchmark_source_verification.json"
    _json_write(replay_audit_path, experiment.replay_audit)
    _json_write(experiment_audit_path, experiment.experiment_audit)
    _json_write(source_verification_path, verification_payload)

    official = experiment.evidence.loc[
        experiment.evidence["family"].eq("official_availability")
    ]
    official_summary = official.iloc[0].to_dict() if len(official) == 1 else None
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(),
        "authority": "research_evidence_only",
        "automatic_promotion": False,
        "production_projection_changed": False,
        "activation_registry_changed": False,
        "target": args.target,
        "seasons": list(seasons),
        "baseline_authority": experiment.replay_audit["baseline_authority"],
        "historical_production_parity_verified": False,
        "frozen_numerical_baseline_sources_verified": verification.verified,
        "frozen_numerical_baseline_source_identity_sha256": (
            verification.source_identity_sha256
        ),
        "evidence_provenance": provenance.model_dump(mode="json"),
        "operator_config": {
            "bootstrap_samples": args.bootstrap_samples,
            "minimum_source_coverage": args.minimum_source_coverage,
            "maximum_fdr_q": args.maximum_fdr_q,
            "minimum_consistency": args.minimum_consistency,
            "minimum_paired_rows": args.minimum_paired_rows,
            "minimum_seasons": args.minimum_seasons,
            "minimum_blocks": args.minimum_blocks,
            "minimum_position_rows": args.minimum_position_rows,
            "maximum_overall_coverage_gap_regression": (
                args.maximum_overall_coverage_gap_regression
            ),
            "maximum_position_coverage_gap_regression": (
                args.maximum_position_coverage_gap_regression
            ),
            "allow_unverified_benchmark_sources": args.allow_unverified_benchmark_sources,
        },
        "inputs": {
            "benchmark_manifest": _input_record(benchmark_manifest),
            "benchmark_sources": list(verification.files),
            "benchmark_root_tree_sha256": _tree_digest(args.benchmark_root),
            "source_coverage": _input_record(coverage_path),
            "evidence_provenance": _input_record(provenance_path),
            "structured_claim_ledger": {
                "root": ledger_root.as_posix(),
                "tree_sha256": _tree_digest(ledger_root),
                "claim_count": ledger_health["claim_count"],
                "integrity_verified": True,
            },
        },
        "replay_audit": experiment.replay_audit,
        "experiment_audit": experiment.experiment_audit,
        "official_availability_result": official_summary,
        "outputs": {
            "replay_features": _input_record(replay_path),
            "point_in_time_features": _input_record(point_in_time_path),
            "incremental_evidence": _input_record(evidence_path),
            "replay_audit": _input_record(replay_audit_path),
            "experiment_audit": _input_record(experiment_audit_path),
            "benchmark_source_verification": _input_record(source_verification_path),
        },
        "interpretation_boundary": (
            "This is an isolated frozen-source historical experiment using current feature/model "
            "code. It is not a byte-for-byte replay of the original historical production feature "
            "matrix. Even an activation-review-eligible result requires explicit manual review and "
            "does not modify production authority."
        ),
    }
    manifest_path = args.output_dir / "run_manifest.json"
    _json_write(manifest_path, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
