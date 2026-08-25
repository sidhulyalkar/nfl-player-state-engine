from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import timedelta
from typing import Literal

import pandas as pd

from player_state_engine.intelligence.structured import (
    StructuredClaim,
    build_state_evidence_snapshots,
    effective_claims_as_of,
)

ResearchEvidenceFamily = Literal["official_availability", "structured_news"]

_FAMILY_PREFIX: dict[ResearchEvidenceFamily, str] = {
    "official_availability": "official_structured_",
    "structured_news": "news_structured_",
}
_LATENT_STATES: tuple[str, ...] = (
    "availability",
    "starter_security",
    "snap_share",
    "route_participation",
    "target_share",
    "carry_share",
    "goal_line_role",
    "third_down_role",
    "role_security",
    "travel_environment",
    "weather_environment",
)
_HIGH_AUTHORITY = {"OFFICIAL", "DIRECT_OBSERVATION", "REPORTED"}


def _is_official_claim(claim: StructuredClaim) -> bool:
    publisher = str(claim.provenance.publisher_type).strip().lower()
    extractor = str(claim.provenance.extractor_version).strip().lower()
    return publisher == "official_availability" or extractor.startswith("official-availability")


def _family_claims(
    claims: Iterable[StructuredClaim], family: ResearchEvidenceFamily
) -> list[StructuredClaim]:
    rows = list(claims)
    if family == "official_availability":
        return [claim for claim in rows if _is_official_claim(claim)]
    return [
        claim
        for claim in rows
        if not _is_official_claim(claim)
        and (
            str(claim.provenance.extractor_version).strip().lower().startswith("news-rules")
            or "source_claim_id" in claim.metadata
        )
    ]


def _prediction_cutoffs(
    frame: pd.DataFrame,
    *,
    prediction_cutoff_column: str,
    kickoff_column: str,
    safety_lag_hours: int,
) -> pd.Series:
    cutoffs = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    if prediction_cutoff_column in frame:
        cutoffs = pd.to_datetime(frame[prediction_cutoff_column], utc=True, errors="coerce")
    if kickoff_column in frame:
        fallback = pd.to_datetime(frame[kickoff_column], utc=True, errors="coerce") - timedelta(
            hours=safety_lag_hours
        )
        cutoffs = cutoffs.fillna(fallback)
    if cutoffs.isna().any():
        missing = int(cutoffs.isna().sum())
        raise ValueError(
            f"Unable to resolve point-in-time intelligence cutoff for {missing} row(s); "
            f"provide {prediction_cutoff_column!r} or valid {kickoff_column!r}."
        )
    return cutoffs


def _zero_features(prefix: str) -> dict[str, object]:
    row: dict[str, object] = {
        f"{prefix}snapshot_found": 0,
        f"{prefix}state_count": 0,
        f"{prefix}claim_count": 0,
        f"{prefix}source_count": 0,
        f"{prefix}high_authority_claim_count": 0,
        f"{prefix}speculation_claim_count": 0,
        f"{prefix}max_conflict": 0.0,
        f"{prefix}mean_conflict": 0.0,
        f"{prefix}research_only": 1,
    }
    for state in _LATENT_STATES:
        row.update(
            {
                f"{prefix}{state}_signal": 0.0,
                f"{prefix}{state}_support": 0.0,
                f"{prefix}{state}_conflict": 0.0,
                f"{prefix}{state}_claim_count": 0,
                f"{prefix}{state}_source_count": 0,
                f"{prefix}{state}_high_authority_claim_count": 0,
                f"{prefix}{state}_speculation_claim_count": 0,
            }
        )
    return row


def attach_canonical_structured_evidence(
    football_features: pd.DataFrame,
    claims: Iterable[StructuredClaim],
    *,
    family: ResearchEvidenceFamily,
    prediction_cutoff_column: str = "prediction_cutoff",
    kickoff_column: str = "gameday",
    safety_lag_hours: int = 1,
) -> pd.DataFrame:
    """Resolve immutable structured claims separately at every prediction cutoff.

    This is a research-only adapter. It deliberately recomputes correction effectiveness and
    recency decay at each football row instead of carrying forward a stale precomputed snapshot.
    It never consults the activation registry and never emits a production-enabled flag.
    """

    if "player_id" not in football_features:
        raise ValueError("Football features require 'player_id' for structured evidence attachment.")
    if safety_lag_hours < 0:
        raise ValueError("safety_lag_hours cannot be negative")

    output = football_features.reset_index(drop=True).copy()
    output["player_id"] = output["player_id"].astype(str)
    cutoffs = _prediction_cutoffs(
        output,
        prediction_cutoff_column=prediction_cutoff_column,
        kickoff_column=kickoff_column,
        safety_lag_hours=safety_lag_hours,
    )
    prefix = _FAMILY_PREFIX[family]
    selected = _family_claims(claims, family)
    by_player: dict[str, list[StructuredClaim]] = defaultdict(list)
    for claim in selected:
        by_player[str(claim.player_id)].append(claim)

    attached_rows: list[dict[str, object]] = []
    for row_index, player_id in enumerate(output["player_id"]):
        cutoff = cutoffs.iloc[row_index]
        player_claims = by_player.get(str(player_id), [])
        eligible = [claim for claim in player_claims if claim.available_at_utc <= cutoff]
        effective = effective_claims_as_of(eligible, as_of_utc=cutoff) if eligible else []
        state_frame = (
            build_state_evidence_snapshots(effective, as_of_utc=cutoff)
            if effective
            else pd.DataFrame()
        )

        values = _zero_features(prefix)
        values[f"{prefix}as_of_utc"] = cutoff
        if effective:
            source_urls = {claim.provenance.source_url for claim in effective}
            values[f"{prefix}snapshot_found"] = 1
            values[f"{prefix}state_count"] = int(len(state_frame))
            values[f"{prefix}claim_count"] = int(len(effective))
            values[f"{prefix}source_count"] = int(len(source_urls))
            values[f"{prefix}high_authority_claim_count"] = int(
                sum(
                    str(claim.provenance.evidence_class) in _HIGH_AUTHORITY
                    for claim in effective
                )
            )
            values[f"{prefix}speculation_claim_count"] = int(
                sum(str(claim.provenance.evidence_class) == "SPECULATION" for claim in effective)
            )
            if not state_frame.empty:
                conflicts = pd.to_numeric(state_frame["conflict_score"], errors="coerce").fillna(0.0)
                values[f"{prefix}max_conflict"] = float(conflicts.max())
                values[f"{prefix}mean_conflict"] = float(conflicts.mean())
                for record in state_frame.to_dict(orient="records"):
                    state = str(record["latent_state"])
                    if state not in _LATENT_STATES:
                        continue
                    values[f"{prefix}{state}_signal"] = float(record["consensus_signal"])
                    values[f"{prefix}{state}_support"] = float(record["support_strength"])
                    values[f"{prefix}{state}_conflict"] = float(record["conflict_score"])
                    values[f"{prefix}{state}_claim_count"] = int(record["claim_count"])
                    values[f"{prefix}{state}_source_count"] = int(record["source_count"])
                    values[f"{prefix}{state}_high_authority_claim_count"] = int(
                        record["high_authority_claim_count"]
                    )
                    values[f"{prefix}{state}_speculation_claim_count"] = int(
                        record["speculation_claim_count"]
                    )
        attached_rows.append(values)

    attached = pd.DataFrame(attached_rows)
    return pd.concat([output, attached], axis=1)
