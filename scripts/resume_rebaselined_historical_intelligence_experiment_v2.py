from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import run_rebaselined_historical_intelligence_experiment_v2 as runner

EXPECTED_BASELINE_IDENTITY = "a036c410e0bb1ec670e3fa0f7d6e14e1433322b6eeabdaa81c25c8daee43a29c"


def _normalize_json(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _normalize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _verified_corpus_builder(*args: object, **kwargs: object):
    corpus = _ORIGINAL_CORPUS_BUILDER(*args, **kwargs)
    corpus.provenance.metadata = _normalize_json(corpus.provenance.metadata)  # type: ignore[assignment]
    return corpus


def _audited_experiment(
    replay,
    claims,
    source_coverage: pd.DataFrame,
    provenance,
    source_verification,
    **kwargs: object,
):
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

    variant_root = Path(str(kwargs.get("output_dir") or "artifacts/intelligence_ablations/v2/variants"))
    output_root = variant_root.parent
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


def _assert_expected_baseline() -> None:
    manifest_path = Path(
        "data/raw/historical_numerical_baseline_v2/NUMERICAL_BASELINE_MANIFEST.json"
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = str(payload.get("identity_sha256") or "")
    if actual != EXPECTED_BASELINE_IDENTITY:
        raise ValueError(
            "Refusing to resume on different numerical bytes: "
            f"expected {EXPECTED_BASELINE_IDENTITY}, found {actual}"
        )
    print(f"BASELINE_IDENTITY_VERIFIED={actual}")


_ORIGINAL_CORPUS_BUILDER = runner.build_historical_intelligence_corpus
_ORIGINAL_EXPERIMENT = runner.run_historical_intelligence_experiment
runner.build_historical_intelligence_corpus = _verified_corpus_builder
runner.run_historical_intelligence_experiment = _audited_experiment


if __name__ == "__main__":
    _assert_expected_baseline()
    sys.argv[0] = "run_rebaselined_historical_intelligence_experiment_v2.py"
    runner.main()
