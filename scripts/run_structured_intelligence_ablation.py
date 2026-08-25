from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pandas as pd

from player_state_engine.config import load_config
from player_state_engine.data.io import read_table, write_table
from player_state_engine.evaluation.intelligence_evidence import (
    run_structured_intelligence_evidence_experiment,
)
from player_state_engine.features.weekly import feature_columns_for_target
from player_state_engine.intelligence.research_features import (
    attach_canonical_structured_evidence,
)
from player_state_engine.intelligence.structured import StructuredClaimLedger


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ledger_digest(root: Path) -> str:
    claim_root = root / "claims"
    digest = hashlib.sha256()
    if not claim_root.exists():
        return digest.hexdigest()
    for path in sorted(claim_root.rglob("*.json")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(_sha256(path).encode("ascii"))
    return digest.hexdigest()


def _git_sha() -> str | None:
    environment_sha = os.environ.get("GITHUB_SHA")
    if environment_sha:
        return environment_sha
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _merge_source_coverage(frame: pd.DataFrame, path: Path | None) -> pd.DataFrame:
    if path is None:
        return frame
    coverage = read_table(path)
    keys = ["season", "week", "player_id"]
    missing = set(keys) - set(coverage.columns)
    if missing:
        raise ValueError(f"Source coverage table missing keys: {sorted(missing)}")
    coverage_columns = [column for column in coverage if column.endswith("_source_covered")]
    if not coverage_columns:
        raise ValueError("Source coverage table contains no '*_source_covered' columns")
    if coverage.duplicated(keys).any():
        raise ValueError("Source coverage table contains duplicate season/week/player_id rows")
    working = frame.copy()
    working["player_id"] = working["player_id"].astype(str)
    coverage = coverage[[*keys, *coverage_columns]].copy()
    coverage["player_id"] = coverage["player_id"].astype(str)
    return working.merge(coverage, on=keys, how="left", validate="many_to_one")


def _drop_legacy_claim_features(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        column
        for column in frame.columns
        if not column.startswith(("availability_", "news_"))
    ]
    return frame[columns].copy()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run research-only incremental structured-intelligence ablations against the frozen "
            "quantile engine. This command never enables or promotes an intelligence family."
        )
    )
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--target", default="fantasy_points_ppr")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/intelligence_ablations/structured"),
    )
    parser.add_argument("--config", type=Path, default=Path("configs/base.yaml"))
    parser.add_argument("--prediction-cutoff-column", default="prediction_cutoff")
    parser.add_argument("--kickoff-column", default="gameday")
    parser.add_argument("--source-coverage", type=Path, default=None)
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
        "--include-legacy-intelligence",
        action="store_true",
        help=(
            "Retain legacy availability_/news_ columns alongside canonical ledger-derived fields. "
            "The default isolates canonical structured evidence."
        ),
    )
    args = parser.parse_args()

    if args.bootstrap_samples <= 0:
        raise ValueError("--bootstrap-samples must be positive")
    if not 0.0 <= args.minimum_source_coverage <= 1.0:
        raise ValueError("--minimum-source-coverage must be between 0 and 1")

    config = load_config(args.config)
    frame = read_table(args.features)
    if not args.include_legacy_intelligence:
        frame = _drop_legacy_claim_features(frame)

    ledger = StructuredClaimLedger(args.ledger_root)
    health = ledger.health()
    if not health["integrity_verified"]:
        raise ValueError(
            "Structured-intelligence ledger failed integrity verification: "
            + "; ".join(str(item) for item in health["integrity_failures"])
        )
    claims = ledger.claims()
    frame = attach_canonical_structured_evidence(
        frame,
        claims,
        family="official_availability",
        prediction_cutoff_column=args.prediction_cutoff_column,
        kickoff_column=args.kickoff_column,
        safety_lag_hours=config.intelligence.safety_lag_hours,
    )
    frame = attach_canonical_structured_evidence(
        frame,
        claims,
        family="structured_news",
        prediction_cutoff_column=args.prediction_cutoff_column,
        kickoff_column=args.kickoff_column,
        safety_lag_hours=config.intelligence.safety_lag_hours,
    )
    frame = _merge_source_coverage(frame, args.source_coverage)

    base_features = feature_columns_for_target(frame, args.target)
    experiment = run_structured_intelligence_evidence_experiment(
        frame,
        base_features,
        args.target,
        replace(config.model, targets=(args.target,)),
        output_dir=args.output_dir / "variants",
        min_train_weeks=config.benchmark.min_train_weeks,
        retrain_every_weeks=config.benchmark.retrain_every_weeks,
        rolling_window=config.benchmark.rolling_window,
        bootstrap_samples=args.bootstrap_samples,
        seed=config.random_seed,
        maximum_fdr_q=args.maximum_fdr_q,
        minimum_consistency=args.minimum_consistency,
        minimum_source_coverage=args.minimum_source_coverage,
        maximum_overall_coverage_gap_regression=args.maximum_overall_coverage_gap_regression,
        maximum_position_coverage_gap_regression=args.maximum_position_coverage_gap_regression,
        minimum_position_rows=args.minimum_position_rows,
        minimum_paired_rows=args.minimum_paired_rows,
        minimum_seasons=args.minimum_seasons,
        minimum_blocks=args.minimum_blocks,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    feature_path = write_table(frame, args.output_dir / "point_in_time_features.parquet")
    evidence_path = write_table(experiment.evidence, args.output_dir / "incremental_evidence.csv")

    input_manifest: dict[str, object] = {
        "features": {
            "path": args.features.as_posix(),
            "bytes": args.features.stat().st_size,
            "sha256": _sha256(args.features),
        },
        "structured_claim_ledger": {
            "root": args.ledger_root.as_posix(),
            "claim_count": health["claim_count"],
            "claims_digest_sha256": _ledger_digest(args.ledger_root),
            "integrity_verified": True,
        },
    }
    if args.source_coverage is not None:
        input_manifest["source_coverage"] = {
            "path": args.source_coverage.as_posix(),
            "bytes": args.source_coverage.stat().st_size,
            "sha256": _sha256(args.source_coverage),
        }

    manifest = {
        "schema_version": 1,
        "git_sha": _git_sha(),
        "target": args.target,
        "authority": "research_evidence_only",
        "automatic_promotion": False,
        "production_projection_changed": False,
        "activation_registry_changed": False,
        "inputs": input_manifest,
        "operator_config": {
            "prediction_cutoff_column": args.prediction_cutoff_column,
            "kickoff_column": args.kickoff_column,
            "safety_lag_hours": config.intelligence.safety_lag_hours,
            "bootstrap_samples_requested": args.bootstrap_samples,
            "bootstrap_samples_minimum_effective": 200,
            "minimum_source_coverage": args.minimum_source_coverage,
            "maximum_fdr_q": args.maximum_fdr_q,
            "minimum_consistency": args.minimum_consistency,
            "minimum_paired_rows": args.minimum_paired_rows,
            "minimum_seasons": args.minimum_seasons,
            "minimum_blocks": args.minimum_blocks,
            "minimum_position_rows": args.minimum_position_rows,
            "maximum_overall_coverage_gap_regression": args.maximum_overall_coverage_gap_regression,
            "maximum_position_coverage_gap_regression": args.maximum_position_coverage_gap_regression,
            "include_legacy_intelligence": args.include_legacy_intelligence,
        },
        "experiment_hierarchy": [
            "numerical_baseline -> official_availability",
            "official_availability -> objective_opportunity",
            "objective_reference -> structured_news",
            "structured_news -> public_player_context",
        ],
        "negative_controls": {
            "identity": "shuffle only the candidate family within season x week x position",
            "time": (
                "move the next same-player same-season candidate-family observation backward; "
                "diagnostic only and never activation-eligible"
            ),
        },
        "multiple_testing": {
            "p_value": "finite_sample_plus_one_season_week_block_bootstrap_tail",
            "correction": "Benjamini-Hochberg across the four incremental family tests",
        },
        "source_coverage_contract": (
            "Claim prevalence is not source coverage. Activation-review eligibility requires an "
            "explicit *_source_covered field on the evaluated player-weeks."
        ),
        "experiments": experiment.evidence.to_dict(orient="records"),
        "outputs": {
            "point_in_time_features": {
                "path": Path(feature_path).as_posix(),
                "sha256": _sha256(Path(feature_path)),
            },
            "incremental_evidence": {
                "path": Path(evidence_path).as_posix(),
                "sha256": _sha256(Path(evidence_path)),
            },
        },
        "interpretation": (
            "eligible_for_activation_review is a research gate only. It cannot enable a feature "
            "family, cannot rewrite production projections, and cannot substitute for downstream "
            "decision evidence or the live 2026 shadow season."
        ),
    }
    manifest_path = args.output_dir / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
