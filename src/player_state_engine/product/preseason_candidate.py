from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from player_state_engine.config import ModelConfig
from player_state_engine.fantasy.preseason import PRESEASON_TARGETS, preseason_feature_columns
from player_state_engine.learning.artifact_registry import (
    ArtifactBundleManifest,
    build_artifact_bundle,
    save_artifact_bundle_manifest,
)
from player_state_engine.models.quantile import QuantileModelBundle

CANDIDATE_MODEL_ID = "preseason_quantile_v017_candidate"
CANDIDATE_TARGET = "preseason_player_values_2026"


def fit_preseason_candidate(
    historical_dataset: pd.DataFrame,
    current_features: pd.DataFrame,
    *,
    model_config: ModelConfig | None = None,
) -> tuple[QuantileModelBundle, pd.DataFrame]:
    """Fit the qualified architecture on completed history and predict a current roster slate."""

    if historical_dataset.empty or current_features.empty:
        raise ValueError("Historical dataset and current features must both be non-empty")
    features = preseason_feature_columns(historical_dataset)
    if not features:
        raise ValueError("No frozen preseason feature columns are available")
    config = model_config or ModelConfig(targets=PRESEASON_TARGETS)
    config = replace(config, targets=tuple(PRESEASON_TARGETS))
    bundle = QuantileModelBundle(config).fit(
        historical_dataset,
        features,
        PRESEASON_TARGETS,
    )
    predictions = bundle.predict(current_features)
    return bundle, predictions


def build_preseason_product_frame(
    predictions: pd.DataFrame,
    *,
    source_cutoff_utc: datetime,
    decision_quantile_policy: str = "pending_uncertainty_qualification",
) -> pd.DataFrame:
    """Create the product-shaped skill-player candidate without claiming production authority."""

    required = {
        "player_id",
        "player_name",
        "position",
        "recent_team",
        "fantasy_points_ppr_q10",
        "fantasy_points_ppr_q50",
        "fantasy_points_ppr_q90",
    }
    missing = required - set(predictions)
    if missing:
        raise ValueError(f"Candidate predictions missing columns: {sorted(missing)}")
    if source_cutoff_utc.tzinfo is None:
        source_cutoff_utc = source_cutoff_utc.replace(tzinfo=UTC)

    out = predictions.copy()
    out["season_points_q10"] = pd.to_numeric(out["fantasy_points_ppr_q10"], errors="coerce")
    out["season_points_q50"] = pd.to_numeric(out["fantasy_points_ppr_q50"], errors="coerce")
    out["season_points_q90"] = pd.to_numeric(out["fantasy_points_ppr_q90"], errors="coerce")
    out["model_version"] = CANDIDATE_MODEL_ID
    out["artifact_authority"] = "challenger"
    out["activation_eligible"] = False
    out["decision_quantile_policy"] = decision_quantile_policy
    out["uncertainty_authority"] = "pending_separate_production_qualification"
    out["projection_source_cutoff_utc"] = source_cutoff_utc.astimezone(UTC).isoformat()
    out["season"] = 2026

    ids = out["player_id"].astype("string").str.strip()
    if ids.isna().any() or ids.eq("").any() or ids.duplicated().any():
        raise ValueError("Candidate product frame requires unique non-empty player_id values")
    q10 = pd.to_numeric(out["season_points_q10"], errors="coerce")
    q50 = pd.to_numeric(out["season_points_q50"], errors="coerce")
    q90 = pd.to_numeric(out["season_points_q90"], errors="coerce")
    if not bool((q10.notna() & q50.notna() & q90.notna()).all()):
        raise ValueError("Candidate product frame contains incomplete PPR quantiles")
    if not bool(((q10 <= q50) & (q50 <= q90)).all()):
        raise ValueError("Candidate product frame contains non-monotonic PPR quantiles")
    return out.sort_values(["position", "recent_team", "player_id"], kind="mergesort").reset_index(drop=True)


def register_candidate_bundle(
    bundle_root: str | Path,
    registry_root: str | Path,
    *,
    model_path: str | Path,
    predictions_path: str | Path,
    roster_path: str | Path,
    evidence_path: str | Path,
    source_cutoff_utc: datetime,
    code_sha: str | None,
    metadata: dict[str, object] | None = None,
) -> ArtifactBundleManifest:
    """Register immutable candidate bytes. This function cannot promote them."""

    if source_cutoff_utc.tzinfo is None:
        source_cutoff_utc = source_cutoff_utc.replace(tzinfo=UTC)
    manifest = build_artifact_bundle(
        bundle_root,
        {
            "model": model_path,
            "player_values": predictions_path,
            "current_roster": roster_path,
            "qualification_evidence": evidence_path,
        },
        artifact_type="preseason_player_values_candidate",
        authority="challenger",
        activation_eligible=False,
        model_id=CANDIDATE_MODEL_ID,
        target=CANDIDATE_TARGET,
        code_sha=code_sha,
        source_cutoff_utc=source_cutoff_utc.astimezone(UTC).isoformat(),
        metadata={
            "season": 2026,
            "automatic_promotion": False,
            **dict(metadata or {}),
        },
    )
    save_artifact_bundle_manifest(manifest, registry_root)
    return manifest
