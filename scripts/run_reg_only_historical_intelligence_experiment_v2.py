from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

import resume_rebaselined_historical_intelligence_experiment_v2 as resume

_ORIGINAL_BUILD_WEEKLY_FEATURES = resume.runner.build_weekly_features


def _build_reg_only_features(*args: object, **kwargs: object) -> pd.DataFrame:
    """Evaluate REG rows while allowing all prior source rows to inform lagged history."""

    features = _ORIGINAL_BUILD_WEEKLY_FEATURES(*args, **kwargs)
    if "season_type" not in features.columns:
        raise ValueError("REG-only experiment requires season_type in the frozen player-stat source")
    season_type = features["season_type"].astype(str).str.upper().str.strip()
    reg = features.loc[season_type.eq("REG")].copy()
    if reg.empty:
        raise ValueError("REG-only experiment produced no regular-season feature rows")
    return reg.reset_index(drop=True)


def _annotate_manifest() -> None:
    root = Path("artifacts/intelligence_ablations/historical_official_v2_reg")
    manifest_path = root / "run_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["evaluation_scope"] = {
        "season_type": "REG",
        "primary_use_case": "fantasy_regular_season",
        "feature_history_context": (
            "Lagged features are calculated from the complete frozen historical source before "
            "the evaluation table is restricted to REG rows. This permits prior postseason "
            "games to inform later regular-season player state while excluding postseason rows "
            "from model fitting and evaluation."
        ),
        "postseason_rows_in_fit_or_evaluation": False,
    }
    payload["interpretation_boundary"] = (
        "Primary fantasy-relevant regular-season experiment on the exact frozen v2 numerical "
        "and injury source bytes. Postseason rows may inform later lagged player histories when "
        "chronologically prior, but they are excluded from model fitting and evaluation. This "
        "remains research evidence only and grants no automatic production authority."
    )
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


resume.runner.build_weekly_features = _build_reg_only_features


if __name__ == "__main__":
    resume._assert_expected_baseline()
    sys.argv[0] = "run_rebaselined_historical_intelligence_experiment_v2.py"
    resume.runner.main()
    _annotate_manifest()
