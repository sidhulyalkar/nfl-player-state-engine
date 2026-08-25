from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import pandas as pd

from player_state_engine.config import load_config
from player_state_engine.data.io import read_table, write_table
from player_state_engine.evaluation.frozen_opportunity import load_frozen_prediction_panel
from player_state_engine.evaluation.historical_intelligence_experiment import (
    FrozenBenchmarkSourceVerification,
    HistoricalFeatureReplay,
    run_historical_intelligence_experiment,
    sha256_file,
)
from player_state_engine.evaluation.intelligence_provenance import IntelligenceEvidenceProvenance
from player_state_engine.features.weekly import feature_columns_for_target
from player_state_engine.intelligence.structured import StructuredClaimLedger

_REPLAY_KEYS = ["season", "week", "game_id", "player_id"]
_COVERAGE_KEYS = ["season", "week", "player_id"]


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


def _input_record(path: Path) -> dict[str, object]:
    return {
        "path": path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _build_archived_replay(
    features: pd.DataFrame,
    source_coverage: pd.DataFrame,
    *,
    benchmark_root: Path,
    seasons: tuple[int, ...],
    target: str,
    outcome_tolerance: float = 1e-8,
) -> HistoricalFeatureReplay:
    frozen = load_frozen_prediction_panel(benchmark_root)
    frozen = frozen.loc[frozen["season"].astype(int).isin(seasons)].copy()
    frozen["player_id"] = frozen["player_id"].astype(str)

    archived = features.loc[features["season"].astype(int).isin(seasons)].copy()
    archived["player_id"] = archived["player_id"].astype(str)
    if "is_projection_row" in archived:
        archived = archived.loc[~archived["is_projection_row"].fillna(False).astype(bool)].copy()

    for label, frame in (("frozen benchmark", frozen), ("archived feature panel", archived)):
        missing = set(_REPLAY_KEYS) - set(frame.columns)
        if missing:
            raise ValueError(f"{label} missing replay keys: {sorted(missing)}")
        if frame.duplicated(_REPLAY_KEYS).any():
            raise ValueError(f"{label} contains duplicate player-game rows")

    frozen_actual = f"actual_{target}"
    if frozen_actual not in frozen or target not in archived:
        raise ValueError("Frozen outcome or archived feature target is unavailable")

    frozen_audit = frozen[
        [
            *_REPLAY_KEYS,
            "position",
            "recent_team",
            "opponent_team",
            frozen_actual,
            *[
                f"{target}_{label}"
                for label in ("q10", "q50", "q90")
                if f"{target}_{label}" in frozen
            ],
        ]
    ].copy()
    frozen_audit = frozen_audit.rename(
        columns={
            "position": "frozen_position",
            "recent_team": "frozen_recent_team",
            "opponent_team": "frozen_opponent_team",
            frozen_actual: "frozen_benchmark_actual",
            **{
                f"{target}_{label}": f"frozen_benchmark_{label}"
                for label in ("q10", "q50", "q90")
                if f"{target}_{label}" in frozen_audit
            },
        }
    )
    replay = frozen_audit.merge(
        archived,
        on=_REPLAY_KEYS,
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    missing_features = replay["_merge"].ne("both")
    if bool(missing_features.any()):
        examples = replay.loc[missing_features, _REPLAY_KEYS].head(5).to_dict(orient="records")
        raise ValueError(
            f"Archived panel is missing {int(missing_features.sum())} frozen player-game rows; "
            f"examples={examples}"
        )
    replay = replay.drop(columns="_merge")

    for frozen_column, archived_column, label in (
        ("frozen_position", "position", "position"),
        ("frozen_recent_team", "recent_team", "recent_team"),
        ("frozen_opponent_team", "opponent_team", "opponent_team"),
    ):
        if archived_column not in replay:
            raise ValueError(f"Archived feature panel is missing {archived_column}")
        mismatch = replay[frozen_column].fillna("").astype(str).ne(
            replay[archived_column].fillna("").astype(str)
        )
        if bool(mismatch.any()):
            raise ValueError(
                f"Archived feature panel disagrees with frozen benchmark {label} for "
                f"{int(mismatch.sum())} row(s)"
            )

    archived_actual = pd.to_numeric(replay[target], errors="coerce")
    benchmark_actual = pd.to_numeric(replay["frozen_benchmark_actual"], errors="coerce")
    if not bool((archived_actual.notna() & benchmark_actual.notna()).all()):
        raise ValueError("Archived target agreement cannot be verified because values are missing")
    differences = (archived_actual - benchmark_actual).abs()
    maximum_difference = float(differences.max()) if len(differences) else 0.0
    mismatch = differences.gt(outcome_tolerance)
    if bool(mismatch.any()):
        raise ValueError(
            f"Archived target outcomes disagree for {int(mismatch.sum())} row(s); "
            f"max_abs_difference={maximum_difference:.12g}"
        )

    coverage_missing = set([*_COVERAGE_KEYS, "prediction_cutoff"]) - set(source_coverage.columns)
    if coverage_missing:
        raise ValueError(f"Historical source coverage missing columns: {sorted(coverage_missing)}")
    coverage = source_coverage[[*_COVERAGE_KEYS, "prediction_cutoff"]].copy()
    coverage["player_id"] = coverage["player_id"].astype(str)
    if coverage.duplicated(_COVERAGE_KEYS).any():
        raise ValueError("Historical source coverage contains duplicate player-week rows")
    replay = replay.merge(coverage, on=_COVERAGE_KEYS, how="left", validate="one_to_one")
    replay["prediction_cutoff"] = pd.to_datetime(
        replay["prediction_cutoff"], utc=True, errors="coerce"
    )
    missing_cutoffs = int(replay["prediction_cutoff"].isna().sum())
    if missing_cutoffs:
        raise ValueError(f"Archived replay is missing {missing_cutoffs} prediction cutoffs")

    base_features = feature_columns_for_target(replay, target)
    if not base_features:
        raise ValueError("Archived replay produced no leakage-safe baseline features")
    audit = {
        "schema_version": 1,
        "authority": "research_evidence_only",
        "baseline_authority": (
            "archived_2026_07_30_feature_panel_verified_player_sources_"
            "schedule_context_equivalent"
        ),
        "historical_production_feature_matrix_persisted": False,
        "contemporaneous_processed_feature_matrix_persisted": True,
        "historical_production_parity_verified": False,
        "automatic_promotion": False,
        "production_projection_changed": False,
        "target": target,
        "evaluation_seasons": list(seasons),
        "rows": int(len(replay)),
        "unique_player_weeks": int(
            replay[["season", "week", "player_id"]].drop_duplicates().shape[0]
        ),
        "unique_season_weeks": int(replay[["season", "week"]].drop_duplicates().shape[0]),
        "base_feature_count": int(len(base_features)),
        "frozen_outcome_agreement_verified": True,
        "frozen_outcome_max_abs_difference": maximum_difference,
        "prediction_cutoff_missing_rows": 0,
        "activation_authority": "blocked_pending_exact_raw_numerical_replay_or_new_frozen_baseline",
    }
    return HistoricalFeatureReplay(frame=replay.reset_index(drop=True), audit=audit)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the official-availability historical ablation on the qualified preserved July "
            "feature panel. Statistical results are research-only and activation review is "
            "forcibly blocked because the original raw player CSV bytes are not retained."
        )
    )
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--panel-qualification", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--benchmark-root", type=Path, default=Path("artifacts/reports/benchmark_real"))
    parser.add_argument("--seasons", nargs="+", type=int, default=[2021, 2022, 2023, 2024])
    parser.add_argument("--target", default="fantasy_points_ppr")
    parser.add_argument("--config", type=Path, default=Path("configs/base.yaml"))
    parser.add_argument("--output-dir", type=Path, required=True)
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

    qualification = json.loads(args.panel_qualification.read_text(encoding="utf-8"))
    if not qualification.get("player_source_identity_verified"):
        raise ValueError("Archived feature panel player-source identity is not verified")
    if not qualification.get("schedule_context_equivalent"):
        raise ValueError("Archived feature panel schedule context is not equivalent")

    seasons = tuple(sorted(set(int(season) for season in args.seasons)))
    config = load_config(args.config)
    features = read_table(args.features)
    coverage_path = args.corpus_root / "source_coverage.parquet"
    provenance_path = args.corpus_root / "evidence_provenance.json"
    ledger_root = args.corpus_root / "ledger"
    source_coverage = read_table(coverage_path)
    provenance = IntelligenceEvidenceProvenance.load(provenance_path)
    ledger = StructuredClaimLedger(ledger_root)
    health = ledger.health()
    if not health["integrity_verified"]:
        raise ValueError("Historical claim ledger failed integrity verification")

    replay = _build_archived_replay(
        features,
        source_coverage,
        benchmark_root=args.benchmark_root,
        seasons=seasons,
        target=args.target,
    )

    source_verification = FrozenBenchmarkSourceVerification(
        verified=False,
        source_identity_sha256=None,
        paths=tuple(),
        files=(
            {
                "name": "archived_feature_panel",
                "path": args.features.as_posix(),
                "verified": True,
                "sha256": sha256_file(args.features),
            },
        ),
        failures=("exact_raw_player_stat_bytes_not_recovered",),
    )
    experiment = run_historical_intelligence_experiment(
        replay,
        ledger.claims(),
        source_coverage,
        provenance,
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
    replay_path = Path(write_table(replay.frame, args.output_dir / "replay_features.parquet"))
    point_in_time_path = Path(
        write_table(experiment.frame, args.output_dir / "point_in_time_features.parquet")
    )
    evidence_path = Path(
        write_table(experiment.evidence, args.output_dir / "incremental_evidence.csv")
    )
    official = experiment.evidence.loc[
        experiment.evidence["family"].eq("official_availability")
    ]
    official_summary = official.iloc[0].to_dict() if len(official) == 1 else None

    manifest = {
        "schema_version": 1,
        "created_by_git_sha": _git_sha(),
        "authority": "research_evidence_only",
        "automatic_promotion": False,
        "production_projection_changed": False,
        "activation_registry_changed": False,
        "target": args.target,
        "seasons": list(seasons),
        "baseline_authority": replay.audit["baseline_authority"],
        "historical_production_parity_verified": False,
        "frozen_numerical_baseline_sources_verified": False,
        "archived_feature_panel_qualification": qualification,
        "replay_audit": replay.audit,
        "experiment_audit": experiment.experiment_audit,
        "official_availability_result": official_summary,
        "inputs": {
            "features": _input_record(args.features),
            "panel_qualification": _input_record(args.panel_qualification),
            "source_coverage": _input_record(coverage_path),
            "evidence_provenance": _input_record(provenance_path),
        },
        "outputs": {
            "replay_features": _input_record(replay_path),
            "point_in_time_features": _input_record(point_in_time_path),
            "incremental_evidence": _input_record(evidence_path),
        },
        "interpretation_boundary": (
            "This experiment uses a preserved July 30 processed feature panel whose player-stat "
            "source identities match the frozen benchmark and whose schedule context is verified "
            "equivalent over the historical evaluation range. The original raw player-stat bytes "
            "are not retained in the artifact, so activation-review eligibility is forcibly blocked "
            "even if the statistical model gates pass."
        ),
    }
    (args.output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
