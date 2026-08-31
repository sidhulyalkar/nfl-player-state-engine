from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from player_state_engine.config import ModelConfig
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.preseason import preseason_feature_columns
from player_state_engine.fantasy.preseason_league_score import (
    LEAGUE_SCORE_TARGET,
    LeagueScoreTargetDiagnostics,
    build_preseason_league_scored_dataset,
)
from player_state_engine.models.conformal import TargetPositionConformalCalibrator
from player_state_engine.models.quantile import QuantileModelBundle

MODEL_ID = "preseason_direct_league_score_v017"
BUNDLE_TARGET = "preseason_multicontract_player_values_2026"
PPR_POLICY = "qualified_distribution"
Q50_POLICY = "q50_only"


@dataclass(frozen=True, slots=True)
class ContractEvidence:
    slug: str
    scoring_contract_id: str
    direct_gate_approved: bool
    uncertainty_gate_approved: bool
    decision_quantile_policy: str
    direct_manifest_sha256: str | None = None
    uncertainty_manifest_sha256: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _load_json(path: str | Path) -> dict[str, object]:
    candidate = Path(path)
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {candidate}")
    return payload


def _league_entry(payload: dict[str, object], slug: str) -> dict[str, object]:
    leagues = payload.get("leagues")
    if not isinstance(leagues, dict) or slug not in leagues:
        raise ValueError(f"Evidence manifest does not contain league {slug!r}")
    entry = leagues[slug]
    if not isinstance(entry, dict):
        raise ValueError(f"Evidence entry for {slug!r} is not an object")
    return entry


def validate_release_evidence(
    direct_manifest_path: str | Path,
    uncertainty_manifest_path: str | Path,
    leagues: dict[str, LeagueConfig],
    *,
    direct_manifest_sha256: str | None = None,
    uncertainty_manifest_sha256: str | None = None,
) -> dict[str, ContractEvidence]:
    """Require the frozen direct-score and uncertainty verdicts before current materialization."""

    direct = _load_json(direct_manifest_path)
    uncertainty = _load_json(uncertainty_manifest_path)
    if direct.get("authority") != "direct_league_score_research_only":
        raise ValueError("Direct-score evidence authority is invalid")
    if direct.get("automatic_promotion") is not False:
        raise ValueError("Direct-score evidence unexpectedly permits automatic promotion")
    if uncertainty.get("authority") != "direct_league_score_uncertainty_research_only":
        raise ValueError("Uncertainty evidence authority is invalid")
    if uncertainty.get("automatic_promotion") is not False:
        raise ValueError("Uncertainty evidence unexpectedly permits automatic promotion")

    output: dict[str, ContractEvidence] = {}
    for slug, config in leagues.items():
        direct_entry = _league_entry(direct, slug)
        uncertainty_entry = _league_entry(uncertainty, slug)
        direct_gate = direct_entry.get("gate")
        if not isinstance(direct_gate, dict) or direct_gate.get("approved") is not True:
            raise ValueError(f"Direct league-score gate is not approved for {slug}")
        decision = uncertainty_entry.get("decision")
        if not isinstance(decision, dict) or "approved" not in decision:
            raise ValueError(f"Uncertainty decision is missing for {slug}")
        uncertainty_approved = bool(decision["approved"])

        scoring = str(config.scoring).strip().lower()
        if scoring == "ppr":
            if not uncertainty_approved:
                raise ValueError(
                    "Frozen PPR uncertainty verdict did not reproduce; refusing 2026 materialization"
                )
            policy = PPR_POLICY
        elif scoring == "half_ppr":
            if uncertainty_approved:
                raise ValueError(
                    "Frozen half-PPR uncertainty verdict changed; require scientific review before "
                    "changing the q50-only release contract"
                )
            policy = Q50_POLICY
        else:
            raise ValueError(f"Current v0.17 release has no qualified direct-score lane for {scoring!r}")

        output[slug] = ContractEvidence(
            slug=slug,
            scoring_contract_id=config.scoring_contract_id,
            direct_gate_approved=True,
            uncertainty_gate_approved=uncertainty_approved,
            decision_quantile_policy=policy,
            direct_manifest_sha256=direct_manifest_sha256,
            uncertainty_manifest_sha256=uncertainty_manifest_sha256,
        )
    return output


def fit_direct_contract_candidate(
    historical_preseason: pd.DataFrame,
    player_stats: pd.DataFrame,
    current_features: pd.DataFrame,
    league: LeagueConfig,
    *,
    model_config: ModelConfig,
) -> tuple[QuantileModelBundle, pd.DataFrame, LeagueScoreTargetDiagnostics]:
    """Fit the historically qualified direct final-score architecture for one scoring contract."""

    training, diagnostics = build_preseason_league_scored_dataset(
        historical_preseason,
        player_stats,
        league,
        target=LEAGUE_SCORE_TARGET,
    )
    features = preseason_feature_columns(training)
    if not features:
        raise ValueError("No frozen preseason feature columns are available")
    config = replace(model_config, targets=(LEAGUE_SCORE_TARGET,))
    model = QuantileModelBundle(config).fit(training, features, (LEAGUE_SCORE_TARGET,))
    predictions = model.predict(current_features)
    return model, predictions, diagnostics


def _current_context(current_features: pd.DataFrame) -> pd.DataFrame:
    columns = [
        column
        for column in (
            "player_id",
            "player_name",
            "position",
            "recent_team",
            "age_at_season_start",
            "rookie",
            "experience_seasons_prior",
            "draft_year",
            "draft_round",
            "draft_pick",
            "roster_status",
        )
        if column in current_features
    ]
    context = current_features.loc[:, columns].copy()
    if "player_id" not in context:
        raise ValueError("Current preseason features require player_id")
    if context["player_id"].astype("string").str.strip().duplicated().any():
        raise ValueError("Current preseason feature context contains duplicate player identities")
    return context


def market_context_from_nfl_hub(snapshot: dict[str, object] | None) -> pd.DataFrame:
    """Extract league-independent current draft-market context from an observational Hub snapshot."""

    columns = ["player_id", "market_rank", "market_adp", "market_identity_source"]
    if not snapshot:
        return pd.DataFrame(columns=columns)
    if snapshot.get("authority") != "observational_nfl_state_only":
        raise ValueError("NFL Hub market context has invalid authority")
    rows = snapshot.get("players")
    if not isinstance(rows, list):
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(rows)
    if frame.empty or "player_id" not in frame:
        return pd.DataFrame(columns=columns)
    available = [column for column in columns if column in frame]
    out = frame.loc[:, available].copy()
    for column in columns:
        if column not in out:
            out[column] = pd.NA
    out["player_id"] = out["player_id"].astype("string").str.strip()
    out = out.loc[out["player_id"].notna() & out["player_id"].ne("")].copy()
    if out["player_id"].duplicated().any():
        raise ValueError("NFL Hub market context contains duplicate player identities")
    return out.loc[:, columns].reset_index(drop=True)


def build_contract_product_frame(
    predictions: pd.DataFrame,
    current_features: pd.DataFrame,
    league: LeagueConfig,
    evidence: ContractEvidence,
    *,
    source_cutoff_utc: datetime,
    market_context: pd.DataFrame | None = None,
    calibrator: TargetPositionConformalCalibrator | None = None,
) -> pd.DataFrame:
    """Build one exact-scoring current player slate with explicit decision-tail authority."""

    if source_cutoff_utc.tzinfo is None:
        raise ValueError("source_cutoff_utc must be timezone-aware")
    if evidence.scoring_contract_id != league.scoring_contract_id:
        raise ValueError("Evidence scoring contract does not match LeagueConfig")
    required = {
        "player_id",
        "position",
        f"{LEAGUE_SCORE_TARGET}_q10",
        f"{LEAGUE_SCORE_TARGET}_q50",
        f"{LEAGUE_SCORE_TARGET}_q90",
    }
    missing = required - set(predictions)
    if missing:
        raise ValueError(f"Direct-score predictions missing columns: {sorted(missing)}")

    raw = predictions.copy()
    final = raw.copy()
    if evidence.decision_quantile_policy == PPR_POLICY:
        if calibrator is None:
            raise ValueError("Qualified-distribution contract requires the reviewed calibrator")
        final = calibrator.transform(raw, LEAGUE_SCORE_TARGET)
    elif evidence.decision_quantile_policy == Q50_POLICY:
        if calibrator is not None:
            raise ValueError("q50-only contract must not apply a rejected tail calibrator")
    else:
        raise ValueError(f"Unsupported decision policy: {evidence.decision_quantile_policy}")

    context = _current_context(current_features)
    out = context.merge(
        final[[
            "player_id",
            "position",
            f"{LEAGUE_SCORE_TARGET}_q10",
            f"{LEAGUE_SCORE_TARGET}_q50",
            f"{LEAGUE_SCORE_TARGET}_q90",
        ]],
        on=["player_id", "position"],
        how="inner",
        validate="one_to_one",
    )
    if len(out) != len(context):
        missing_ids = sorted(set(context["player_id"].astype(str)) - set(out["player_id"].astype(str)))
        raise ValueError(f"Direct-score predictions do not cover current roster universe: {missing_ids[:10]}")

    for label in (10, 50, 90):
        source = f"{LEAGUE_SCORE_TARGET}_q{label}"
        values = pd.to_numeric(out[source], errors="coerce")
        if values.isna().any():
            raise ValueError(f"Current direct-score predictions contain missing q{label} values")
        out[f"league_season_points_q{label}"] = values.astype(float)
        out[f"season_points_q{label}"] = values.astype(float)

    q10 = out["league_season_points_q10"]
    q50 = out["league_season_points_q50"]
    q90 = out["league_season_points_q90"]
    if not bool(((q10 <= q50) & (q50 <= q90)).all()):
        raise ValueError("Current direct-score prediction quantiles are not monotonic")

    raw_by_id = raw.set_index("player_id")
    for label in (10, 50, 90):
        raw_column = f"{LEAGUE_SCORE_TARGET}_q{label}"
        out[f"raw_league_season_points_q{label}"] = out["player_id"].map(
            pd.to_numeric(raw_by_id[raw_column], errors="coerce")
        )

    if market_context is not None and not market_context.empty:
        out = out.merge(market_context, on="player_id", how="left", validate="one_to_one")
    else:
        out["market_rank"] = pd.NA
        out["market_adp"] = pd.NA
        out["market_identity_source"] = pd.NA

    generated = datetime.now(UTC)
    out["scoring_contract_id"] = league.scoring_contract_id
    out["scoring_name"] = str(league.scoring).strip().lower()
    out["tight_end_premium"] = float(league.tight_end_premium)
    out["league_scoring_exact"] = True
    out["league_scoring_coverage"] = 1.0
    out["league_scoring_approximate"] = False
    out["league_scoring_fallback"] = False
    out["decision_quantile_policy"] = evidence.decision_quantile_policy
    out["decision_tail_authorized"] = evidence.decision_quantile_policy == PPR_POLICY
    out["uncertainty_authority"] = (
        "earlier_season_conformal_qualified"
        if evidence.decision_quantile_policy == PPR_POLICY
        else "q50_only_tails_not_qualified"
    )
    out["model_version"] = MODEL_ID
    out["artifact_authority"] = "challenger"
    out["activation_eligible"] = False
    out["data_mode"] = "CURRENT_PRESEASON_DIRECT_LEAGUE_SCORE_CHALLENGER"
    out["season"] = int(pd.to_numeric(current_features["season"], errors="coerce").dropna().iloc[0])
    out["source_cutoff"] = source_cutoff_utc.astimezone(UTC).isoformat()
    out["projection_source_cutoff_utc"] = source_cutoff_utc.astimezone(UTC).isoformat()
    out["prediction_timestamp"] = generated.isoformat()
    out["age"] = pd.to_numeric(out.get("age_at_season_start"), errors="coerce")
    return out.sort_values(["position", "recent_team", "player_id"], kind="mergesort").reset_index(drop=True)


def combine_contract_product_frames(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Combine exact contract slates while requiring one common current player universe."""

    if len(frames) < 2:
        raise ValueError("The current release requires at least two scoring-contract slates")
    player_sets: dict[str, set[str]] = {}
    for slug, frame in frames.items():
        if frame.empty:
            raise ValueError(f"Contract frame {slug!r} is empty")
        required = {"scoring_contract_id", "player_id", "decision_quantile_policy"}
        missing = required - set(frame)
        if missing:
            raise ValueError(f"Contract frame {slug!r} missing columns: {sorted(missing)}")
        ids = frame["player_id"].astype("string").str.strip()
        if ids.isna().any() or ids.eq("").any() or ids.duplicated().any():
            raise ValueError(f"Contract frame {slug!r} requires unique non-empty player_id values")
        contract_ids = set(frame["scoring_contract_id"].astype(str))
        if len(contract_ids) != 1:
            raise ValueError(f"Contract frame {slug!r} has mixed scoring_contract_id values")
        policies = set(frame["decision_quantile_policy"].astype(str))
        if len(policies) != 1:
            raise ValueError(f"Contract frame {slug!r} has mixed decision policies")
        player_sets[slug] = set(ids.astype(str))

    reference_slug = next(iter(player_sets))
    reference = player_sets[reference_slug]
    mismatched = {
        slug: {
            "missing": sorted(reference - values)[:10],
            "extra": sorted(values - reference)[:10],
        }
        for slug, values in player_sets.items()
        if values != reference
    }
    if mismatched:
        raise ValueError(f"Scoring-contract current player universes differ: {mismatched}")

    combined = pd.concat(frames.values(), ignore_index=True)
    if combined.duplicated(["scoring_contract_id", "player_id"]).any():
        raise ValueError("Combined product contains duplicate scoring-contract/player identities")
    return combined.sort_values(
        ["scoring_contract_id", "position", "recent_team", "player_id"],
        kind="mergesort",
    ).reset_index(drop=True)
