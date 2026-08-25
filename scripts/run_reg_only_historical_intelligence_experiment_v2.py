from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

import resume_rebaselined_historical_intelligence_experiment_v2 as resume

_ORIGINAL_BUILD_WEEKLY_FEATURES = resume.runner.build_weekly_features
_ORIGINAL_CORPUS_BUILDER = resume.runner.build_historical_intelligence_corpus
_PRACTICE_STATUS_ALIASES = {
    "full participation in practice": "full participation",
    "limited participation in practice": "limited participation",
    "did not participate in practice": "did not participate",
}
_PRACTICE_ROWS_NORMALIZED = 0


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


def _build_corpus_with_nflverse_practice_aliases(*args: object, **kwargs: object):
    """Normalize the long-form practice strings present in frozen nflverse injury releases."""

    global _PRACTICE_ROWS_NORMALIZED
    injuries = kwargs.get("injuries")
    if isinstance(injuries, pd.DataFrame) and not injuries.empty:
        if "practice_status" not in injuries.columns:
            raise ValueError("Frozen injury archive is missing practice_status")
        normalized = injuries.copy()
        text = normalized["practice_status"].astype("string").str.strip().str.lower()
        mapped = text.map(_PRACTICE_STATUS_ALIASES)
        mask = mapped.notna()
        _PRACTICE_ROWS_NORMALIZED = int(mask.sum())
        if _PRACTICE_ROWS_NORMALIZED == 0:
            raise ValueError(
                "Frozen nflverse injury archive contains no recognized long-form practice statuses"
            )
        normalized.loc[mask, "practice_status"] = mapped.loc[mask].astype(str)
        kwargs["injuries"] = normalized
    return _ORIGINAL_CORPUS_BUILDER(*args, **kwargs)


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
    payload["historical_injury_adapter"] = {
        "nflverse_long_form_practice_statuses_normalized": True,
        "normalized_rows": _PRACTICE_ROWS_NORMALIZED,
        "aliases": _PRACTICE_STATUS_ALIASES,
        "reason": (
            "nflverse historical injury releases use long-form values ending in 'in practice'; "
            "the canonical historical adapter currently recognizes the equivalent shorter forms."
        ),
    }
    payload["interpretation_boundary"] = (
        "Primary fantasy-relevant regular-season experiment on the exact frozen v2 numerical "
        "and injury source bytes. Long-form nflverse practice-status aliases are normalized before "
        "canonical evidence construction. Postseason rows may inform later lagged player histories "
        "when chronologically prior, but they are excluded from model fitting and evaluation. This "
        "remains research evidence only and grants no automatic production authority."
    )
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


resume.runner.build_weekly_features = _build_reg_only_features
resume.runner.build_historical_intelligence_corpus = _build_corpus_with_nflverse_practice_aliases


if __name__ == "__main__":
    resume._assert_expected_baseline()
    sys.argv[0] = "run_rebaselined_historical_intelligence_experiment_v2.py"
    resume.runner.main()
    _annotate_manifest()
