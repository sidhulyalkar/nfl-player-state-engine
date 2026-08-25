from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from player_state_engine.data.historical import read_historical_table
from player_state_engine.data.io import write_table
from player_state_engine.evaluation.frozen_opportunity import load_frozen_prediction_panel
from player_state_engine.evaluation.historical_intelligence_corpus import (
    HISTORICAL_NFLVERSE_INJURY_MAX_SEASON,
    build_historical_intelligence_corpus,
    verify_source_archive_manifest,
)
from player_state_engine.intelligence.availability import OfficialAvailabilityEvidence
from player_state_engine.intelligence.official_claims import canonicalize_official_availability
from player_state_engine.intelligence.structured import StructuredClaimLedger

_SEASON_RE = re.compile(r"(?:19|20)\d{2}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(root: Path) -> str:
    if not root.exists():
        raise FileNotFoundError(f"benchmark root unavailable: {root}")
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise ValueError(f"benchmark root contains no files: {root}")
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(_sha256(path).encode("ascii"))
    return digest.hexdigest()


def _season(path: Path) -> int | None:
    match = _SEASON_RE.search(path.name)
    return int(match.group(0)) if match else None


def _paths_for_seasons(paths: list[Path], seasons: set[int]) -> list[Path]:
    return [path for path in paths if _season(path) in seasons]


def _concat(paths: list[Path]) -> pd.DataFrame | None:
    frames = [read_historical_table(path) for path in paths if path.is_file()]
    return pd.concat(frames, ignore_index=True) if frames else None


def _source_urls(manifest: pd.DataFrame, paths: list[Path]) -> dict[int, str]:
    if "url" not in manifest:
        return {}
    working = manifest.copy()
    working["_basename"] = working["path"].astype(str).map(lambda value: Path(value).name)
    result: dict[int, str] = {}
    for path in paths:
        season = _season(path)
        if season is None:
            continue
        matches = working.loc[working["_basename"].eq(path.name)]
        if len(matches) == 1 and str(matches.iloc[0]["url"]).strip():
            result[season] = str(matches.iloc[0]["url"])
    return result


def _combined_archive_identity(
    source_identity: str | None,
    *,
    schedules_sha256: str,
    benchmark_sha256: str,
) -> str | None:
    if not source_identity:
        return None
    digest = hashlib.sha256()
    digest.update(source_identity.encode("ascii"))
    digest.update(schedules_sha256.encode("ascii"))
    digest.update(benchmark_sha256.encode("ascii"))
    return digest.hexdigest()


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
        "root": root.as_posix(),
        "official_evidence_rows": len(typed),
        "canonical_claims": len(claims),
        "created": created,
        "unchanged": unchanged,
        "health": ledger.health(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a frozen point-in-time historical official-intelligence corpus with separate "
            "evidence, source-coverage, provenance, and immutable structured-claim artifacts."
        )
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/raw/historical_sources"),
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=None,
        help="Defaults to <data-dir>/SOURCE_MANIFEST.csv.",
    )
    parser.add_argument(
        "--benchmark-root",
        type=Path,
        default=Path("artifacts/reports/benchmark_real"),
    )
    parser.add_argument(
        "--schedules",
        type=Path,
        default=Path("data/raw/nflverse_full/schedules.parquet"),
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=[2021, 2022, 2023, 2024],
    )
    parser.add_argument(
        "--include-depth-charts",
        action="store_true",
        help="Add timestamped depth-chart evidence when a recent pre-cutoff snapshot exists.",
    )
    parser.add_argument("--cutoff-hours-before", type=float, default=1.5)
    parser.add_argument("--depth-maximum-age-days", type=float, default=14.0)
    parser.add_argument(
        "--allow-unverified-archive",
        action="store_true",
        help=(
            "Research-only escape hatch. The corpus is still built, but provenance cannot reach "
            "Tier 2 when archive checks fail."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/intelligence_corpus/historical_official"),
    )
    args = parser.parse_args()

    seasons = sorted(set(int(season) for season in args.seasons))
    if not seasons:
        raise ValueError("--seasons cannot be empty")
    if any(season > HISTORICAL_NFLVERSE_INJURY_MAX_SEASON for season in seasons):
        raise ValueError(
            "The nflverse historical injury corpus is certified only through 2024. "
            "Build 2025+ official availability from a separately archived prospective source."
        )
    if not args.schedules.is_file():
        raise FileNotFoundError(f"schedules unavailable: {args.schedules}")

    source_manifest_path = args.source_manifest or (args.data_dir / "SOURCE_MANIFEST.csv")
    if not source_manifest_path.is_file():
        if not args.allow_unverified_archive:
            raise FileNotFoundError(
                f"source manifest unavailable: {source_manifest_path}. "
                "Use --allow-unverified-archive only for exploratory Tier-0/1 research."
            )
        source_manifest = pd.DataFrame(columns=["path", "sha256", "status", "url"])
    else:
        source_manifest = pd.read_csv(source_manifest_path)

    season_set = set(seasons)
    injury_paths = _paths_for_seasons(sorted(args.data_dir.glob("injuries_*.csv")), season_set)
    if not injury_paths:
        raise FileNotFoundError(
            "No requested historical injury files found. Run scripts/acquire_historical_sources.py first."
        )
    depth_paths = (
        _paths_for_seasons(sorted(args.data_dir.glob("depth_charts_*.rds")), season_set)
        if args.include_depth_charts
        else []
    )
    evidence_paths = [*injury_paths, *depth_paths]

    if source_manifest.empty:
        verification_verified = False
        verification_identity = None
        verification_files: tuple[dict[str, object], ...] = ()
        verification_failures = ("source_manifest_unavailable",)
    else:
        verification = verify_source_archive_manifest(evidence_paths, source_manifest)
        verification_verified = verification.verified
        verification_identity = verification.archive_identity_sha256
        verification_files = verification.files
        verification_failures = verification.failures
    if not verification_verified and not args.allow_unverified_archive:
        raise ValueError(
            "Historical source archive verification failed: " + "; ".join(verification_failures)
        )

    schedules_sha256 = _sha256(args.schedules)
    benchmark_sha256 = _tree_digest(args.benchmark_root)
    archive_identity = _combined_archive_identity(
        verification_identity,
        schedules_sha256=schedules_sha256,
        benchmark_sha256=benchmark_sha256,
    )

    panel = load_frozen_prediction_panel(args.benchmark_root)
    panel = panel.loc[pd.to_numeric(panel["season"], errors="coerce").isin(seasons)].copy()
    if panel.empty:
        raise ValueError(f"Frozen prediction panel has no rows for requested seasons: {seasons}")
    schedules = read_historical_table(args.schedules)
    injuries = _concat(injury_paths)
    depth_charts = _concat(depth_paths) if depth_paths else None

    corpus = build_historical_intelligence_corpus(
        panel,
        schedules,
        injuries=injuries,
        depth_charts=depth_charts,
        include_injuries=True,
        include_depth_charts=args.include_depth_charts,
        cutoff_hours_before=args.cutoff_hours_before,
        depth_maximum_age_days=args.depth_maximum_age_days,
        source_archive_verified=verification_verified,
        archive_identity_sha256=archive_identity,
        injury_source_urls=_source_urls(source_manifest, injury_paths),
        depth_source_urls=_source_urls(source_manifest, depth_paths),
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = Path(
        write_table(corpus.official_evidence, args.output_dir / "official_evidence.parquet")
    )
    coverage_path = Path(
        write_table(corpus.source_coverage, args.output_dir / "source_coverage.parquet")
    )
    provenance_path = args.output_dir / "evidence_provenance.json"
    provenance_path.write_text(
        corpus.provenance.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    audit_path = args.output_dir / "corpus_audit.json"
    audit_path.write_text(
        json.dumps(corpus.audit, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    ledger = _persist_ledger(corpus.official_evidence, args.output_dir / "ledger")
    health = ledger.get("health")
    if not isinstance(health, dict):
        raise ValueError("Historical structured-claim ledger returned invalid health metadata")
    if not health.get("integrity_verified"):
        failures = health.get("integrity_failures", [])
        raise ValueError(
            "Historical structured-claim ledger failed integrity verification: "
            + "; ".join(str(item) for item in failures)
        )

    run_manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "authority": "research_evidence_only",
        "automatic_promotion": False,
        "production_projection_changed": False,
        "activation_registry_changed": False,
        "requested_seasons": seasons,
        "inputs": {
            "source_manifest": {
                "path": source_manifest_path.as_posix(),
                "sha256": _sha256(source_manifest_path) if source_manifest_path.is_file() else None,
            },
            "evidence_files": list(verification_files),
            "archive_verification": {
                "verified": verification_verified,
                "failures": list(verification_failures),
                "source_archive_identity_sha256": verification_identity,
                "combined_frozen_identity_sha256": archive_identity,
            },
            "schedules": {
                "path": args.schedules.as_posix(),
                "sha256": schedules_sha256,
            },
            "benchmark_root": {
                "path": args.benchmark_root.as_posix(),
                "tree_sha256": benchmark_sha256,
            },
        },
        "operator_config": {
            "cutoff_hours_before": args.cutoff_hours_before,
            "include_depth_charts": args.include_depth_charts,
            "depth_maximum_age_days": args.depth_maximum_age_days,
            "nflverse_injury_certified_through_season": HISTORICAL_NFLVERSE_INJURY_MAX_SEASON,
            "allow_unverified_archive": args.allow_unverified_archive,
        },
        "provenance": corpus.provenance.model_dump(mode="json"),
        "audit": corpus.audit,
        "ledger": ledger,
        "outputs": {
            "official_evidence": {
                "path": evidence_path.as_posix(),
                "sha256": _sha256(evidence_path),
            },
            "source_coverage": {
                "path": coverage_path.as_posix(),
                "sha256": _sha256(coverage_path),
            },
            "evidence_provenance": {
                "path": provenance_path.as_posix(),
                "sha256": _sha256(provenance_path),
            },
            "corpus_audit": {
                "path": audit_path.as_posix(),
                "sha256": _sha256(audit_path),
            },
        },
        "next_step": (
            "Feed ledger/, source_coverage.parquet, and evidence_provenance.json into the "
            "structured-intelligence ablation operator. Tier-2 corpus status is evidence-input "
            "authority only and is not model promotion."
        ),
    }
    manifest_path = args.output_dir / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(run_manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(run_manifest, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
