from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pandas as pd

from player_state_engine.config import load_config
from player_state_engine.data.io import read_table, write_table
from player_state_engine.evaluation.historical_intelligence_corpus import (
    build_historical_intelligence_corpus,
    verify_source_archive_manifest,
)
from player_state_engine.evaluation.historical_intelligence_experiment import (
    FrozenBenchmarkSourceVerification,
    HistoricalFeatureReplay,
    run_historical_intelligence_experiment,
    sha256_file,
)
from player_state_engine.features.weekly import build_weekly_features, feature_columns_for_target
from player_state_engine.intelligence.availability import OfficialAvailabilityEvidence
from player_state_engine.intelligence.official_claims import canonicalize_official_availability
from player_state_engine.intelligence.structured import StructuredClaimLedger

_SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}


def _git_sha() -> str | None:
    value = os.environ.get("GITHUB_SHA")
    if value:
        return value
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(sha256_file(path).encode("ascii"))
    return digest.hexdigest()


def _input_record(path: Path) -> dict[str, object]:
    return {
        "path": path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _load_manifest(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise ValueError(f"Invalid manifest: {path}")
    return payload


def _verify_numerical_manifest(
    manifest_path: Path,
) -> tuple[dict[str, object], dict[str, Path]]:
    manifest = _load_manifest(manifest_path)
    paths: dict[str, Path] = {}
    failures: list[str] = []
    for raw in manifest["files"]:
        if not isinstance(raw, dict) or not raw.get("name") or not raw.get("path"):
            failures.append("invalid_source_record")
            continue
        name = str(raw["name"])
        path = Path(str(raw["path"]))
        paths[name] = path
        if not path.is_file():
            failures.append(f"missing:{name}")
            continue
        if path.stat().st_size != int(raw.get("bytes", -1)):
            failures.append(f"bytes:{name}")
        if sha256_file(path) != str(raw.get("sha256", "")):
            failures.append(f"sha256:{name}")
    if failures:
        raise ValueError("Numerical baseline manifest verification failed: " + ", ".join(failures))

    expected_identity = str(manifest.get("identity_sha256") or "")
    digest = hashlib.sha256()
    for raw in sorted(manifest["files"], key=lambda item: str(item["name"])):
        digest.update(str(raw["name"]).encode("utf-8"))
        digest.update(str(raw["sha256"]).encode("ascii"))
        digest.update(str(raw["bytes"]).encode("ascii"))
    actual_identity = digest.hexdigest()
    if not expected_identity or actual_identity != expected_identity:
        raise ValueError("Numerical baseline identity digest does not match its manifest")
    return manifest, paths


def _injury_archive(
    root: Path,
) -> tuple[pd.DataFrame, dict[int, str], object]:
    manifest_path = root / "SOURCE_MANIFEST.csv"
    manifest = pd.read_csv(manifest_path)
    available = manifest.loc[manifest["status"].astype(str).str.startswith("available")].copy()
    injury_rows = available.loc[available["name"].astype(str).str.startswith("injuries_")]
    paths = [Path(path) for path in injury_rows["path"].astype(str)]
    verification = verify_source_archive_manifest(paths, manifest)
    if not verification.verified or not verification.archive_identity_sha256:
        raise ValueError(
            "Historical injury archive failed content verification: "
            + "; ".join(verification.failures)
        )
    frames = [read_table(path) for path in paths]
    injuries = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    urls: dict[int, str] = {}
    for row in injury_rows.to_dict(orient="records"):
        name = str(row["name"])
        try:
            season = int(name.rsplit("_", 1)[1])
        except (IndexError, ValueError):
            continue
        urls[season] = str(row.get("url") or "")
    return injuries, urls, verification


def _persist_ledger(evidence: pd.DataFrame, root: Path) -> dict[str, object]:
    records = evidence.astype(object).where(pd.notna(evidence), None).to_dict(orient="records")
    typed = [OfficialAvailabilityEvidence.model_validate(record) for record in records]
    claims = canonicalize_official_availability(typed)
    ledger = StructuredClaimLedger(root)
    created = 0
    unchanged = 0
    for claim in claims:
        if ledger.save(claim):
            created += 1
        else:
            unchanged += 1
    return {
        "official_evidence_rows": len(typed),
        "canonical_claims": len(claims),
        "created": created,
        "unchanged": unchanged,
        "health": ledger.health(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a fresh content-addressed multi-season official-availability experiment on a newly "
            "frozen historical numerical baseline. This is a new experiment identity, not a replay "
            "of the July benchmark and not historical production parity."
        )
    )
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
    parser.add_argument("--seasons", nargs="+", type=int, default=[2020, 2021, 2022, 2023, 2024])
    parser.add_argument("--target", default="fantasy_points_ppr")
    parser.add_argument("--config", type=Path, default=Path("configs/base.yaml"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/intelligence_ablations/historical_official_v2"),
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
    args = parser.parse_args()

    seasons = tuple(sorted(set(int(season) for season in args.seasons)))
    if not seasons:
        raise ValueError("--seasons cannot be empty")
    config = load_config(args.config)

    numerical_manifest_path = args.numerical_root / "NUMERICAL_BASELINE_MANIFEST.json"
    numerical_manifest, numerical_paths = _verify_numerical_manifest(numerical_manifest_path)
    player_names = [f"player_stats_{season}" for season in seasons]
    missing_player_sources = [name for name in player_names if name not in numerical_paths]
    if missing_player_sources:
        raise ValueError(f"Numerical baseline is missing player sources: {missing_player_sources}")
    if "schedules" not in numerical_paths:
        raise ValueError("Numerical baseline is missing schedules")

    raw_stats = pd.concat(
        [read_table(numerical_paths[name]) for name in player_names],
        ignore_index=True,
        sort=False,
    )
    schedules = read_table(numerical_paths["schedules"])
    features = build_weekly_features(raw_stats, schedules=schedules, config=config.features)
    features = features.loc[
        features["season"].astype(int).isin(seasons)
        & features["position"].astype(str).str.upper().isin(_SKILL_POSITIONS)
        & ~features["is_projection_row"].fillna(False).astype(bool)
    ].copy()
    if features.empty:
        raise ValueError("Newly frozen numerical baseline produced no skill-position feature rows")
    panel_keys = ["season", "week", "game_id", "player_id", "recent_team"]
    panel = features[panel_keys].copy()
    if panel.duplicated(["season", "week", "player_id"]).any():
        raise ValueError("Numerical v2 panel contains duplicate player-week identities")

    injuries, injury_urls, injury_verification = _injury_archive(args.injury_root)
    corpus = build_historical_intelligence_corpus(
        panel,
        schedules,
        injuries=injuries,
        include_injuries=True,
        include_depth_charts=False,
        cutoff_hours_before=1.5,
        source_archive_verified=True,
        archive_identity_sha256=injury_verification.archive_identity_sha256,
        injury_source_urls=injury_urls,
    )
    if corpus.source_coverage["prediction_cutoff"].isna().any():
        raise ValueError("v2 corpus contains missing prediction cutoffs")

    corpus_root = args.output_dir / "corpus"
    corpus_root.mkdir(parents=True, exist_ok=True)
    evidence_path = Path(
        write_table(corpus.official_evidence, corpus_root / "official_evidence.parquet")
    )
    coverage_path = Path(
        write_table(corpus.source_coverage, corpus_root / "source_coverage.parquet")
    )
    provenance_path = corpus_root / "evidence_provenance.json"
    provenance_path.write_text(
        corpus.provenance.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    ledger_root = corpus_root / "ledger"
    ledger_audit = _persist_ledger(corpus.official_evidence, ledger_root)
    if not ledger_audit["health"]["integrity_verified"]:
        raise ValueError("v2 structured claim ledger failed integrity verification")

    replay_frame = features.merge(
        corpus.source_coverage[["season", "week", "player_id", "prediction_cutoff"]],
        on=["season", "week", "player_id"],
        how="left",
        validate="one_to_one",
    )
    replay_frame["prediction_cutoff"] = pd.to_datetime(
        replay_frame["prediction_cutoff"], utc=True, errors="coerce"
    )
    if replay_frame["prediction_cutoff"].isna().any():
        raise ValueError("v2 numerical replay contains missing prediction cutoffs")
    base_features = feature_columns_for_target(replay_frame, args.target)
    if not base_features:
        raise ValueError("v2 numerical replay produced no leakage-safe model features")

    baseline_id = str(numerical_manifest["baseline_id"])
    replay = HistoricalFeatureReplay(
        frame=replay_frame.reset_index(drop=True),
        audit={
            "schema_version": 1,
            "authority": "research_evidence_only",
            "baseline_authority": f"newly_frozen_historical_numerical_baseline:{baseline_id}",
            "historical_production_feature_matrix_persisted": False,
            "historical_production_parity_verified": False,
            "automatic_promotion": False,
            "production_projection_changed": False,
            "target": args.target,
            "evaluation_seasons": list(seasons),
            "rows": int(len(replay_frame)),
            "unique_player_weeks": int(
                replay_frame[["season", "week", "player_id"]].drop_duplicates().shape[0]
            ),
            "unique_season_weeks": int(
                replay_frame[["season", "week"]].drop_duplicates().shape[0]
            ),
            "base_feature_count": int(len(base_features)),
            "prediction_cutoff_missing_rows": 0,
            "numerical_baseline_identity_sha256": numerical_manifest["identity_sha256"],
            "numerical_source_bytes_verified": True,
        },
    )
    source_verification = FrozenBenchmarkSourceVerification(
        verified=True,
        source_identity_sha256=str(numerical_manifest["identity_sha256"]),
        paths=tuple(
            (str(row["name"]), str(row["path"]))
            for row in numerical_manifest["files"]
            if isinstance(row, dict)
        ),
        files=tuple(
            {
                **row,
                "verified": True,
                "actual_sha256": row["sha256"],
                "actual_bytes": row["bytes"],
            }
            for row in numerical_manifest["files"]
            if isinstance(row, dict)
        ),
        failures=tuple(),
    )
    ledger = StructuredClaimLedger(ledger_root)
    experiment = run_historical_intelligence_experiment(
        replay,
        ledger.claims(),
        corpus.source_coverage,
        corpus.provenance,
        source_verification,
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

    args.output_dir.mkdir(parents=True, exist_ok=True)
    features_path = Path(write_table(features, args.output_dir / "weekly_features_v2.parquet"))
    point_in_time_path = Path(
        write_table(experiment.frame, args.output_dir / "point_in_time_features.parquet")
    )
    incremental_path = Path(
        write_table(experiment.evidence, args.output_dir / "incremental_evidence.csv")
    )
    official = experiment.evidence.loc[
        experiment.evidence["family"].eq("official_availability")
    ]
    official_summary = official.iloc[0].to_dict() if len(official) == 1 else None

    manifest = {
        "schema_version": 1,
        "created_by_git_sha": _git_sha(),
        "experiment_id": f"historical-official-availability-v2-{baseline_id}",
        "authority": "research_evidence_only",
        "automatic_promotion": False,
        "production_projection_changed": False,
        "activation_registry_changed": False,
        "historical_production_parity_verified": False,
        "new_numerical_baseline_fully_content_addressed": True,
        "target": args.target,
        "seasons": list(seasons),
        "baseline_authority": replay.audit["baseline_authority"],
        "numerical_baseline": numerical_manifest,
        "injury_archive": {
            "verified": injury_verification.verified,
            "identity_sha256": injury_verification.archive_identity_sha256,
            "files": list(injury_verification.files),
        },
        "source_coverage_preflight": {
            "rows": int(len(corpus.source_coverage)),
            "official_source_coverage": float(
                corpus.source_coverage["official_availability_source_covered"].mean()
            ),
            "injury_source_coverage": float(
                corpus.source_coverage["official_injury_report_source_covered"].mean()
            ),
            "evidence_prevalence": float(
                corpus.source_coverage["official_availability_evidence_found"].mean()
            ),
            "covered_seasons": corpus.audit["covered_seasons"],
            "evidence_tier": corpus.audit["evidence_tier"],
        },
        "replay_audit": replay.audit,
        "experiment_audit": experiment.experiment_audit,
        "official_availability_result": official_summary,
        "ledger_audit": ledger_audit,
        "inputs": {
            "numerical_manifest": _input_record(numerical_manifest_path),
            "injury_manifest": _input_record(args.injury_root / "SOURCE_MANIFEST.csv"),
            "evidence_provenance": _input_record(provenance_path),
            "source_coverage": _input_record(coverage_path),
        },
        "outputs": {
            "weekly_features": _input_record(features_path),
            "official_evidence": _input_record(evidence_path),
            "point_in_time_features": _input_record(point_in_time_path),
            "incremental_evidence": _input_record(incremental_path),
            "corpus_tree_sha256": _tree_digest(corpus_root),
        },
        "interpretation_boundary": (
            "This is a newly frozen historical experiment with exact input hashes and a pinned "
            "schedule commit. It can support manual review of incremental official-availability "
            "evidence for the newly frozen baseline if the statistical and coverage gates pass. "
            "It is not a replay of the July benchmark and does not claim historical production "
            "feature parity or automatic production authority."
        ),
    }
    (args.output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
