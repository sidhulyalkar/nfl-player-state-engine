from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Final

from player_state_engine.intelligence.availability import OfficialAvailabilityEvidence
from player_state_engine.intelligence.structured import ClaimProvenance, StructuredClaim

_PRACTICE_DIRECTION: Final[dict[str, float]] = {
    "full": 0.65,
    "limited": -0.35,
    "did_not_participate": -0.80,
    "not_listed": 0.45,
    "unknown": 0.0,
}
_GAME_DIRECTION: Final[dict[str, float]] = {
    "active": 1.0,
    "questionable": -0.35,
    "doubtful": -0.80,
    "out": -1.0,
    "ir": -1.0,
    "pup": -1.0,
    "suspended": -1.0,
    "unknown": 0.0,
}
_TRANSACTION_DIRECTION: Final[dict[str, float]] = {
    "activated": 0.85,
    "signed": 0.55,
    "waived": -0.90,
    "released": -0.90,
    "ir": -1.0,
    "pup": -1.0,
    "suspended": -1.0,
    "unknown": 0.0,
}
_DEPTH_DIRECTION: Final[dict[str, float]] = {
    "starter": 0.90,
    "committee": 0.05,
    "backup": -0.60,
    "practice_squad": -0.95,
    "unknown": 0.0,
}


def _claim_id(evidence_id: str, claim_type: str) -> str:
    payload = json.dumps(
        {"evidence_id": evidence_id, "claim_type": claim_type},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _provenance(
    evidence: OfficialAvailabilityEvidence,
    *,
    supporting_evidence: str,
) -> ClaimProvenance:
    return ClaimProvenance(
        source_url=evidence.source_url,
        publisher_type="official_availability",
        evidence_class="OFFICIAL",
        authored_at_utc=evidence.observed_at_utc,
        collected_at_utc=evidence.observed_at_utc,
        available_at_utc=evidence.observed_at_utc,
        availability_basis="collected",
        supporting_evidence=supporting_evidence,
        extractor_version="official-availability-adapter-v1",
        extractor_confidence=1.0,
        source_reliability=evidence.source_reliability,
        document_id=evidence.evidence_id,
        caveats=[
            "Official evidence is point-in-time input, not a guarantee of game participation or workload.",
            "Downstream activation still requires frozen ablation and manual promotion.",
        ],
    )


def _claim(
    evidence: OfficialAvailabilityEvidence,
    *,
    claim_type: str,
    domain: str,
    latent_state: str,
    direction: float,
    magnitude: float | None = None,
    half_life_days: float,
    supporting_evidence: str,
    metadata: dict[str, object] | None = None,
) -> StructuredClaim:
    bounded_direction = max(-1.0, min(float(direction), 1.0))
    bounded_magnitude = (
        min(abs(bounded_direction), 1.0)
        if magnitude is None
        else max(0.0, min(float(magnitude), 1.0))
    )
    return StructuredClaim(
        claim_id=_claim_id(evidence.evidence_id, claim_type),
        player_id=evidence.player_id,
        claim_type=claim_type,
        domain=domain,  # type: ignore[arg-type]
        latent_state=latent_state,
        direction=bounded_direction,
        magnitude=bounded_magnitude,
        decay_half_life_days=half_life_days,
        provenance=_provenance(evidence, supporting_evidence=supporting_evidence),
        metadata={
            "source_evidence_id": evidence.evidence_id,
            "official_event_type": evidence.event_type,
            **(metadata or {}),
        },
    )


def structured_claims_from_official_availability(
    evidence: OfficialAvailabilityEvidence,
) -> list[StructuredClaim]:
    """Convert one normalized first-party event into canonical structured claims."""

    event_type = evidence.event_type
    claims: list[StructuredClaim] = []

    if event_type == "practice_participation":
        status = evidence.practice_status
        direction = _PRACTICE_DIRECTION[status]
        claims.append(
            _claim(
                evidence,
                claim_type="official_practice_status",
                domain="availability",
                latent_state="availability",
                direction=direction,
                half_life_days=3.0,
                supporting_evidence=evidence.evidence_text
                or f"Official practice participation status: {status}.",
                metadata={"practice_status": status},
            )
        )
    elif event_type == "game_designation":
        status = evidence.game_status
        direction = _GAME_DIRECTION[status]
        claims.append(
            _claim(
                evidence,
                claim_type="official_game_designation",
                domain="availability",
                latent_state="availability",
                direction=direction,
                half_life_days=2.0,
                supporting_evidence=evidence.evidence_text
                or f"Official game designation: {status}.",
                metadata={"game_status": status},
            )
        )
    elif event_type == "inactive_list":
        inactive = bool(evidence.is_inactive)
        claims.append(
            _claim(
                evidence,
                claim_type="official_inactive_status",
                domain="availability",
                latent_state="availability",
                direction=-1.0 if inactive else 0.6,
                half_life_days=1.0,
                supporting_evidence=evidence.evidence_text
                or f"Official inactive list status: {'inactive' if inactive else 'not inactive'}.",
                metadata={"is_inactive": inactive},
            )
        )
    elif event_type == "injured_reserve":
        status = evidence.transaction_status
        direction = -1.0 if status in {"ir", "pup"} or evidence.game_status in {"ir", "pup"} else 0.0
        claims.append(
            _claim(
                evidence,
                claim_type="official_reserve_status",
                domain="availability",
                latent_state="availability",
                direction=direction,
                half_life_days=21.0,
                supporting_evidence=evidence.evidence_text
                or f"Official reserve status: transaction={status}, game={evidence.game_status}.",
                metadata={
                    "transaction_status": status,
                    "game_status": evidence.game_status,
                },
            )
        )
    elif event_type == "transaction":
        status = evidence.transaction_status
        claims.append(
            _claim(
                evidence,
                claim_type="official_transaction_status",
                domain="availability",
                latent_state="availability",
                direction=_TRANSACTION_DIRECTION[status],
                half_life_days=14.0,
                supporting_evidence=evidence.evidence_text
                or f"Official transaction status: {status}.",
                metadata={"transaction_status": status},
            )
        )
    elif event_type == "depth_chart":
        role = evidence.depth_role
        claims.append(
            _claim(
                evidence,
                claim_type="official_depth_role",
                domain="role",
                latent_state="starter_security",
                direction=_DEPTH_DIRECTION[role],
                half_life_days=10.0,
                supporting_evidence=evidence.evidence_text
                or f"Official depth role: {role}; rank={evidence.depth_rank}.",
                metadata={"depth_role": role, "depth_rank": evidence.depth_rank},
            )
        )
    elif event_type == "coach_workload":
        fraction = evidence.expected_workload_fraction
        if fraction is not None:
            direction = 2.0 * float(fraction) - 1.0
            claims.append(
                _claim(
                    evidence,
                    claim_type="official_coach_workload",
                    domain="opportunity",
                    latent_state="snap_share",
                    direction=direction,
                    magnitude=abs(direction),
                    half_life_days=5.0,
                    supporting_evidence=evidence.evidence_text
                    or f"Official coach workload expectation: {float(fraction):.3f}.",
                    metadata={"expected_workload_fraction": float(fraction)},
                )
            )
    return claims


def canonicalize_official_availability(
    evidence: Iterable[OfficialAvailabilityEvidence],
) -> list[StructuredClaim]:
    claims: list[StructuredClaim] = []
    for item in evidence:
        claims.extend(structured_claims_from_official_availability(item))
    return claims
