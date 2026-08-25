from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import run_rebaselined_historical_intelligence_experiment_v2 as runner

EXPECTED_BASELINE_IDENTITY = "a036c410e0bb1ec670e3fa0f7d6e14e1433322b6eeabdaa81c25c8daee43a29c"
_ORIGINAL_BUILD_WEEKLY_FEATURES = runner.build_weekly_features
_ORIGINAL_EXPERIMENT = runner.run_historical_intelligence_experiment


def _numerical_root_from_argv() -> Path:
    default = Path("data/raw/historical_numerical_baseline_v2")
    for index, argument in enumerate(sys.argv[:-1]):
        if argument == "--numerical-root":
            return Path(sys.argv[index + 1])
    return default


def _assert_expected_baseline() -> None:
    manifest_path = _numerical_root_from_argv() / "NUMERICAL_BASELINE_MANIFEST.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = str(payload.get("identity_sha256") or "")
    if actual != EXPECTED_BASELINE_IDENTITY:
        raise ValueError(
            "Refusing to run the registered REG experiment on different numerical bytes: "
            f"expected {EXPECTED_BASELINE_IDENTITY}, found {actual}"
        )
    print(f"BASELINE_IDENTITY_VERIFIED={actual}")


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


def _annotate_manifest() -> None:
    output_root = Path("artifacts/intelligence_ablations/historical_official_v2_reg")
    for index, argument in enumerate(sys.argv[:-1]):
        if argument == "--output-dir":
            output_root = Path(sys.argv[index + 1])
            break
    manifest_path = output_root / "run_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
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
    payload["registered_numerical_baseline_identity_sha256"] = EXPECTED_BASELINE_IDENTITY
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
        "numerical baseline and verified injury archive. The result may support manual activation "
        "review only if every preregistered statistical, consistency, negative-control, calibration, "
        "source-coverage, and evidence-tier gate passes. It never grants automatic production authority."
    )
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


runner.build_weekly_features = _build_reg_only_features
runner.run_historical_intelligence_experiment = _experiment_with_prefit_coverage


if __name__ == "__main__":
    _assert_expected_baseline()
    sys.argv[0] = "run_rebaselined_historical_intelligence_experiment_v2.py"
    runner.main()
    _annotate_manifest()
