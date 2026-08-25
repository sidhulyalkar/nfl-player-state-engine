from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import resume_rebaselined_historical_intelligence_experiment_v2 as resume

# Final nflverse games.csv values whose historical 1.5-hour as-of provenance is not established.
_UNVERIFIED_CONTEXT_COLUMNS = ("spread_line", "total_line", "roof", "temp", "wind")
_ORIGINAL_BUILD_WEEKLY_FEATURES = resume.runner.build_weekly_features


def _build_reg_without_unverified_context(*args: object, **kwargs: object) -> pd.DataFrame:
    """Build chronological histories, keep REG targets, then remove unverified game context."""

    features = _ORIGINAL_BUILD_WEEKLY_FEATURES(*args, **kwargs)
    if "season_type" not in features.columns:
        raise ValueError("REG sensitivity requires season_type in the frozen player-stat source")
    season_type = features["season_type"].astype(str).str.upper().str.strip()
    regular = features.loc[season_type.eq("REG")].copy()
    if regular.empty:
        raise ValueError("REG sensitivity produced no regular-season feature rows")

    present = [column for column in _UNVERIFIED_CONTEXT_COLUMNS if column in regular.columns]
    if set(present) != set(_UNVERIFIED_CONTEXT_COLUMNS):
        missing = sorted(set(_UNVERIFIED_CONTEXT_COLUMNS) - set(present))
        raise ValueError(
            "Pregame-context sensitivity expected all registered context columns before removal; "
            f"missing={missing}"
        )
    return regular.drop(columns=list(_UNVERIFIED_CONTEXT_COLUMNS)).reset_index(drop=True)


def _output_root_from_argv() -> Path:
    default = Path("artifacts/intelligence_ablations/historical_official_v2_reg_context_sensitivity")
    for index, argument in enumerate(sys.argv[:-1]):
        if argument == "--output-dir":
            return Path(sys.argv[index + 1])
    return default


def _annotate_manifest() -> None:
    root = _output_root_from_argv()
    manifest_path = root / "run_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["evaluation_scope"] = {
        "season_type": "REG",
        "primary_use_case": "fantasy_regular_season_sensitivity",
        "postseason_rows_in_fit_or_evaluation": False,
    }
    payload["pregame_context_sensitivity"] = {
        "excluded_columns": list(_UNVERIFIED_CONTEXT_COLUMNS),
        "reason": (
            "The frozen nflverse games table documents these as game-level line/weather/roof values "
            "but does not provide historical as-of timestamps proving the final values were known at "
            "the registered 1.5-hour prediction cutoff. They are removed from every model variant in "
            "this sensitivity analysis while all frozen source bytes, outcomes, folds, controls, and "
            "statistical gates remain unchanged."
        ),
        "changes_primary_registered_experiment": False,
    }
    payload["interpretation_boundary"] = (
        "Secondary leakage-sensitivity analysis only. It repeats the registered REG official-"
        "availability experiment after removing final-table betting line and game-condition fields "
        "whose exact 1.5-hour historical availability is unverified. Agreement with the primary run "
        "strengthens robustness; disagreement blocks activation and requires a truly timestamped "
        "pregame context source. No automatic production authority is granted."
    )
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


resume.runner.build_weekly_features = _build_reg_without_unverified_context


if __name__ == "__main__":
    resume._assert_expected_baseline()
    sys.argv[0] = "run_rebaselined_historical_intelligence_experiment_v2.py"
    resume.runner.main()
    _annotate_manifest()
