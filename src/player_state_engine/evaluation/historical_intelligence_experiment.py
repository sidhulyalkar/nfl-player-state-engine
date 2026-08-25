from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from player_state_engine.config import AppConfig
from player_state_engine.evaluation.frozen_opportunity import load_frozen_prediction_panel
from player_state_engine.evaluation.intelligence_evidence import (
    IntelligenceEvidenceRun,
    run_structured_intelligence_evidence_experiment,
)
from player_state_engine.evaluation.intelligence_provenance import IntelligenceEvidenceProvenance
from player_state_engine.features.weekly import build_weekly_features, feature_columns_for_target
from player_state_engine.intelligence.research_features import attach_canonical_structured_evidence
from player_state_engine.intelligence.structured import StructuredClaim

_REPLAY_KEYS = ["season", "week", "game_id", "player_id"]
_COVERAGE_KEYS = ["season", "week", "player_id"]


@dataclass(slots=True, frozen=True)
class FrozenBenchmarkSourceVerification:
    verified: bool
    source_identity_sha256: str | None
    paths: tuple[tuple[str, str], ...]
    files: tuple[dict[str, object], ...]
    failures: tuple[str, ...]

    def path_for(self, name: str) -> Path:
        mapping = dict(self.paths)
        if name not in mapping:
            raise KeyError(f"Frozen benchmark source {name!r} was not resolved")
        return Path(mapping[name])


@dataclass(slots=True)
class HistoricalFeatureReplay:
    frame: pd.DataFrame
    audit: dict[str, object]


@dataclass(slots=True)
class HistoricalIntelligenceExperiment:
    frame: pd.DataFrame
    evidence: pd.DataFrame
    replay_audit: dict[str, object]
    experiment_audit: dict[str, object]
    runs: dict[str, object]


def sha256_file(path: str | Path) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_frozen_benchmark_manifest(path: str | Path) -> dict[str, object]:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Frozen benchmark manifest is unreadable: {path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise ValueError("Frozen benchmark manifest must contain a source list")
    return payload


def _required_source_names(
    manifest: dict[str, object], seasons: tuple[int, ...]
) -> tuple[str, ...]:
    if not seasons:
        raise ValueError("Historical replay requires at least one evaluation season")
    available = {
        str(row.get("name"))
        for row in manifest.get("sources", [])
        if isinstance(row, dict) and row.get("name")
    }
    evaluation = sorted(set(int(season) for season in seasons))
    history_start = evaluation[0] - 1
    required_seasons = list(evaluation)
    if f"player_stats_{history_start}" in available:
        required_seasons.insert(0, history_start)
    return tuple([*(f"player_stats_{season}" for season in required_seasons), "schedules"])


def _source_records(manifest: dict[str, object]) -> dict[str, dict[str, object]]:
    output: dict[str, dict[str, object]] = {}
    for raw in manifest.get("sources", []):
        if not isinstance(raw, dict):
            raise ValueError("Frozen benchmark source records must be objects")
        name = str(raw.get("name", "")).strip()
        if not name:
            raise ValueError("Frozen benchmark source record is missing a name")
        if name in output:
            raise ValueError(f"Duplicate frozen benchmark source record: {name}")
        output[name] = raw
    return output


def _local_source_path(source_dir: Path, record: dict[str, object]) -> Path:
    url = str(record.get("url", "")).strip()
    name = str(record.get("name", "")).strip()
    basename = Path(urlparse(url).path).name if url else ""
    candidates: list[Path] = []
    if basename:
        candidates.append(source_dir / basename)
        suffix = Path(basename).suffix
        if suffix:
            candidates.append(source_dir / f"{name}{suffix}")
    else:
        candidates.append(source_dir / name)
    for candidate in dict.fromkeys(candidates):
        if candidate.is_file():
            return candidate
    return candidates[0]


def verify_frozen_benchmark_sources(
    manifest_path: str | Path,
    source_dir: str | Path,
    *,
    seasons: tuple[int, ...] = (2021, 2022, 2023, 2024),
) -> FrozenBenchmarkSourceVerification:
    """Verify source bytes used to reconstruct the historical numerical baseline.

    The benchmark manifest is content-addressed. A source URL being reachable is
    not sufficient because mutable upstream files can change after a benchmark
    was frozen. Exact SHA-256 and byte-count agreement is required for a verified
    replay source set.
    """

    manifest = load_frozen_benchmark_manifest(manifest_path)
    records = _source_records(manifest)
    required = _required_source_names(manifest, seasons)
    source_dir = Path(source_dir)
    files: list[dict[str, object]] = []
    paths: list[tuple[str, str]] = []
    failures: list[str] = []

    for name in required:
        record = records.get(name)
        if record is None:
            failures.append(f"manifest_source_missing:{name}")
            continue
        path = _local_source_path(source_dir, record)
        paths.append((name, path.as_posix()))
        expected_sha = str(record.get("sha256", "")).strip().lower()
        expected_bytes_raw = record.get("bytes")
        try:
            expected_bytes = int(expected_bytes_raw) if expected_bytes_raw is not None else None
        except (TypeError, ValueError):
            failures.append(f"manifest_bytes_invalid:{name}")
            expected_bytes = None

        if not path.is_file():
            failures.append(f"source_file_missing:{name}:{path.name}")
            files.append(
                {
                    "name": name,
                    "path": path.as_posix(),
                    "verified": False,
                    "expected_sha256": expected_sha or None,
                    "actual_sha256": None,
                    "expected_bytes": expected_bytes,
                    "actual_bytes": None,
                }
            )
            continue

        actual_sha = sha256_file(path)
        actual_bytes = path.stat().st_size
        verified = bool(expected_sha and actual_sha == expected_sha)
        if not expected_sha:
            failures.append(f"manifest_sha256_missing:{name}")
        elif actual_sha != expected_sha:
            failures.append(f"source_sha256_mismatch:{name}")
        if expected_bytes is not None and actual_bytes != expected_bytes:
            failures.append(f"source_bytes_mismatch:{name}")
            verified = False
        files.append(
            {
                "name": name,
                "path": path.as_posix(),
                "verified": verified,
                "expected_sha256": expected_sha or None,
                "actual_sha256": actual_sha,
                "expected_bytes": expected_bytes,
                "actual_bytes": actual_bytes,
            }
        )

    all_verified = not failures and len(files) == len(required) and all(
        bool(row["verified"]) for row in files
    )
    identity: str | None = None
    if all_verified:
        digest = hashlib.sha256()
        for row in sorted(files, key=lambda item: str(item["name"])):
            digest.update(str(row["name"]).encode("utf-8"))
            digest.update(str(row["actual_sha256"]).encode("ascii"))
        identity = digest.hexdigest()

    return FrozenBenchmarkSourceVerification(
        verified=all_verified,
        source_identity_sha256=identity,
        paths=tuple(paths),
        files=tuple(files),
        failures=tuple(dict.fromkeys(failures)),
    )


def build_historical_feature_replay(
    player_stats: pd.DataFrame,
    schedules: pd.DataFrame,
    source_coverage: pd.DataFrame,
    *,
    benchmark_root: str | Path,
    seasons: tuple[int, ...] = (2021, 2022, 2023, 2024),
    target: str = "fantasy_points_ppr",
    config: AppConfig | None = None,
    outcome_tolerance: float = 1e-8,
) -> HistoricalFeatureReplay:
    """Rebuild current-code point-in-time features on the frozen benchmark universe.

    This is deliberately *not* described as the original benchmark feature
    matrix. The historical benchmark did not persist that matrix. Instead, the
    function rebuilds the current feature pipeline from content-addressed raw
    inputs and then restricts it to the exact frozen out-of-sample player-week
    universe. Realized target values must agree with the frozen benchmark.
    """

    if outcome_tolerance < 0:
        raise ValueError("outcome_tolerance cannot be negative")
    evaluation_seasons = tuple(sorted(set(int(season) for season in seasons)))
    if not evaluation_seasons:
        raise ValueError("Historical feature replay requires at least one season")

    frozen = load_frozen_prediction_panel(benchmark_root)
    frozen = frozen.loc[frozen["season"].astype(int).isin(evaluation_seasons)].copy()
    if frozen.empty:
        raise ValueError(f"Frozen benchmark contains no rows for seasons={evaluation_seasons}")
    frozen["player_id"] = frozen["player_id"].astype(str)

    weekly = build_weekly_features(
        player_stats,
        schedules=schedules,
        config=config.features if config is not None else None,
    )
    weekly = weekly.loc[weekly["season"].astype(int).isin(evaluation_seasons)].copy()
    weekly["player_id"] = weekly["player_id"].astype(str)

    for label, frame in (("frozen benchmark", frozen), ("rebuilt feature frame", weekly)):
        missing = set(_REPLAY_KEYS) - set(frame.columns)
        if missing:
            raise ValueError(f"{label} missing replay keys: {sorted(missing)}")
        if frame.duplicated(_REPLAY_KEYS).any():
            raise ValueError(f"{label} contains duplicate player-game rows")

    frozen_actual = f"actual_{target}"
    if frozen_actual not in frozen:
        raise ValueError(f"Frozen benchmark does not contain target outcome {frozen_actual!r}")
    if target not in weekly:
        raise ValueError(f"Rebuilt feature frame does not contain target {target!r}")

    frozen_columns = [*_REPLAY_KEYS, "position", frozen_actual]
    for label in ("q10", "q50", "q90"):
        column = f"{target}_{label}"
        if column in frozen:
            frozen_columns.append(column)
    frozen_audit = frozen[frozen_columns].copy().rename(
        columns={
            "position": "frozen_position",
            frozen_actual: "frozen_benchmark_actual",
            **{
                f"{target}_{label}": f"frozen_benchmark_{label}"
                for label in ("q10", "q50", "q90")
                if f"{target}_{label}" in frozen_columns
            },
        }
    )

    replay = frozen_audit.merge(
        weekly,
        on=_REPLAY_KEYS,
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    missing_features = replay["_merge"].ne("both")
    if bool(missing_features.any()):
        examples = replay.loc[missing_features, _REPLAY_KEYS].head(5).to_dict(orient="records")
        raise ValueError(
            f"Current feature builder could not reconstruct {int(missing_features.sum())} frozen "
            f"player-game row(s); examples={examples}"
        )
    replay = replay.drop(columns="_merge")

    position_mismatch = replay["frozen_position"].astype(str).ne(replay["position"].astype(str))
    if bool(position_mismatch.any()):
        raise ValueError(
            "Frozen benchmark and rebuilt features disagree on player position for "
            f"{int(position_mismatch.sum())} row(s)"
        )

    rebuilt_actual = pd.to_numeric(replay[target], errors="coerce")
    benchmark_actual = pd.to_numeric(replay["frozen_benchmark_actual"], errors="coerce")
    finite = rebuilt_actual.notna() & benchmark_actual.notna()
    if not bool(finite.all()):
        raise ValueError("Frozen benchmark outcome agreement cannot be verified because values are missing")
    differences = (rebuilt_actual - benchmark_actual).abs()
    maximum_difference = float(differences.max()) if len(differences) else 0.0
    mismatched_outcomes = differences.gt(outcome_tolerance)
    if bool(mismatched_outcomes.any()):
        raise ValueError(
            "Rebuilt target outcomes disagree with the frozen benchmark for "
            f"{int(mismatched_outcomes.sum())} row(s); max_abs_difference={maximum_difference:.12g}"
        )

    coverage_missing = set([*_COVERAGE_KEYS, "prediction_cutoff"]) - set(source_coverage.columns)
    if coverage_missing:
        raise ValueError(f"Historical source coverage missing columns: {sorted(coverage_missing)}")
    coverage = source_coverage[[*_COVERAGE_KEYS, "prediction_cutoff"]].copy()
    coverage["player_id"] = coverage["player_id"].astype(str)
    if coverage.duplicated(_COVERAGE_KEYS).any():
        raise ValueError("Historical source coverage contains duplicate player-week rows")
    replay = replay.merge(
        coverage,
        on=_COVERAGE_KEYS,
        how="left",
        validate="one_to_one",
    )
    replay["prediction_cutoff"] = pd.to_datetime(
        replay["prediction_cutoff"], utc=True, errors="coerce"
    )
    missing_cutoffs = int(replay["prediction_cutoff"].isna().sum())
    if missing_cutoffs:
        raise ValueError(
            f"Historical feature replay is missing {missing_cutoffs} schedule-derived prediction cutoff(s)"
        )

    base_features = feature_columns_for_target(replay, target)
    if not base_features:
        raise ValueError("Historical feature replay produced no leakage-safe baseline features")

    audit = {
        "schema_version": 1,
        "authority": "research_evidence_only",
        "baseline_authority": "current_feature_builder_frozen_source_replay",
        "historical_production_feature_matrix_persisted": False,
        "historical_production_parity_verified": False,
        "automatic_promotion": False,
        "production_projection_changed": False,
        "target": target,
        "evaluation_seasons": list(evaluation_seasons),
        "rows": int(len(replay)),
        "unique_player_weeks": int(replay[["season", "week", "player_id"]].drop_duplicates().shape[0]),
        "unique_season_weeks": int(replay[["season", "week"]].drop_duplicates().shape[0]),
        "base_feature_count": int(len(base_features)),
        "frozen_outcome_agreement_verified": True,
        "frozen_outcome_max_abs_difference": maximum_difference,
        "prediction_cutoff_missing_rows": 0,
    }
    return HistoricalFeatureReplay(frame=replay.reset_index(drop=True), audit=audit)


def _merge_source_coverage(frame: pd.DataFrame, source_coverage: pd.DataFrame) -> pd.DataFrame:
    coverage_columns = [
        column for column in source_coverage.columns if column.endswith("_source_covered")
    ]
    if not coverage_columns:
        raise ValueError("Historical source coverage contains no '*_source_covered' columns")
    coverage = source_coverage[[*_COVERAGE_KEYS, *coverage_columns]].copy()
    coverage["player_id"] = coverage["player_id"].astype(str)
    if coverage.duplicated(_COVERAGE_KEYS).any():
        raise ValueError("Historical source coverage contains duplicate player-week rows")
    output = frame.copy()
    embedded = [column for column in output if column.endswith("_source_covered")]
    if embedded:
        raise ValueError(
            "Replay features must not embed source-coverage authority before the explicit join: "
            + ", ".join(sorted(embedded))
        )
    output["player_id"] = output["player_id"].astype(str)
    return output.merge(coverage, on=_COVERAGE_KEYS, how="left", validate="one_to_one")


def _append_activation_blocker(evidence: pd.DataFrame, blocker: str) -> pd.DataFrame:
    output = evidence.copy()
    if "eligible_for_activation_review" not in output:
        return output
    for index in output.index:
        raw = output.at[index, "activation_review_blockers"]
        blockers = list(raw) if isinstance(raw, list) else []
        if blocker not in blockers:
            blockers.append(blocker)
        output.at[index, "activation_review_blockers"] = blockers
        output.at[index, "eligible_for_activation_review"] = False
    return output


def run_historical_intelligence_experiment(
    replay: HistoricalFeatureReplay,
    claims: list[StructuredClaim],
    source_coverage: pd.DataFrame,
    provenance: IntelligenceEvidenceProvenance,
    source_verification: FrozenBenchmarkSourceVerification,
    *,
    config: AppConfig,
    target: str = "fantasy_points_ppr",
    output_dir: str | Path | None = None,
    bootstrap_samples: int = 2000,
    minimum_source_coverage: float = 0.80,
    maximum_fdr_q: float = 0.10,
    minimum_consistency: float = 0.55,
    minimum_paired_rows: int = 250,
    minimum_seasons: int = 2,
    minimum_blocks: int = 8,
    minimum_position_rows: int = 50,
    maximum_overall_coverage_gap_regression: float = 0.02,
    maximum_position_coverage_gap_regression: float = 0.05,
) -> HistoricalIntelligenceExperiment:
    """Run the real frozen official-intelligence ablation against current code.

    Model statistics and source-evidence authority stay separate. If the raw
    numerical baseline inputs cannot be verified against the frozen benchmark
    manifest, the experiment may still be inspected but activation-review
    eligibility is forcibly disabled.
    """

    frame = attach_canonical_structured_evidence(
        replay.frame,
        claims,
        family="official_availability",
        prediction_cutoff_column="prediction_cutoff",
        kickoff_column="gameday",
        safety_lag_hours=config.intelligence.safety_lag_hours,
    )
    frame = attach_canonical_structured_evidence(
        frame,
        claims,
        family="structured_news",
        prediction_cutoff_column="prediction_cutoff",
        kickoff_column="gameday",
        safety_lag_hours=config.intelligence.safety_lag_hours,
    )
    frame = _merge_source_coverage(frame, source_coverage)
    base_features = feature_columns_for_target(frame, target)

    experiment: IntelligenceEvidenceRun = run_structured_intelligence_evidence_experiment(
        frame,
        base_features,
        target,
        config.model,
        evidence_tier=provenance.tier,
        output_dir=output_dir,
        min_train_weeks=config.benchmark.min_train_weeks,
        retrain_every_weeks=config.benchmark.retrain_every_weeks,
        rolling_window=config.benchmark.rolling_window,
        bootstrap_samples=bootstrap_samples,
        seed=config.random_seed,
        maximum_fdr_q=maximum_fdr_q,
        minimum_consistency=minimum_consistency,
        minimum_source_coverage=minimum_source_coverage,
        maximum_overall_coverage_gap_regression=maximum_overall_coverage_gap_regression,
        maximum_position_coverage_gap_regression=maximum_position_coverage_gap_regression,
        minimum_position_rows=minimum_position_rows,
        minimum_paired_rows=minimum_paired_rows,
        minimum_seasons=minimum_seasons,
        minimum_blocks=minimum_blocks,
    )
    evidence = experiment.evidence
    if not source_verification.verified:
        evidence = _append_activation_blocker(
            evidence,
            "frozen_numerical_baseline_sources_unverified",
        )

    official = evidence.loc[evidence["family"].eq("official_availability")]
    official_eligible = bool(
        not official.empty and official["eligible_for_activation_review"].astype(bool).any()
    )
    experiment_audit = {
        "schema_version": 1,
        "authority": "research_evidence_only",
        "automatic_promotion": False,
        "production_projection_changed": False,
        "activation_registry_changed": False,
        "target": target,
        "evidence_tier": int(provenance.tier),
        "frozen_numerical_baseline_sources_verified": source_verification.verified,
        "frozen_numerical_baseline_source_identity_sha256": (
            source_verification.source_identity_sha256
        ),
        "historical_production_parity_verified": False,
        "baseline_authority": replay.audit["baseline_authority"],
        "official_availability_eligible_for_manual_activation_review": official_eligible,
        "interpretation": (
            "This run tests incremental official-intelligence value using the current feature/model "
            "code on the frozen historical player-week universe. It is not a byte-for-byte replay "
            "of the historical production feature matrix, which was not persisted."
        ),
    }
    return HistoricalIntelligenceExperiment(
        frame=frame,
        evidence=evidence,
        replay_audit=replay.audit,
        experiment_audit=experiment_audit,
        runs=experiment.runs,
    )
