from __future__ import annotations

import hashlib
import json
import math
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, field_validator, model_validator

from player_state_engine.intelligence.news import NewsClaim

ClaimDomain = Literal[
    "availability",
    "opportunity",
    "role",
    "environment",
    "public_context",
]
ClaimStatus = Literal["asserted", "retracted", "superseded"]
AuthorityClass = Literal[
    "OFFICIAL",
    "DIRECT_OBSERVATION",
    "REPORTED",
    "COACH_QUOTE",
    "PLAYER_QUOTE",
    "ANALYSIS",
    "SPECULATION",
]
AvailabilityBasis = Literal["published", "collected"]

_AUTHORITY_WEIGHT: dict[str, float] = {
    "OFFICIAL": 1.00,
    "DIRECT_OBSERVATION": 0.95,
    "REPORTED": 0.88,
    "COACH_QUOTE": 0.82,
    "PLAYER_QUOTE": 0.70,
    "ANALYSIS": 0.55,
    "SPECULATION": 0.30,
}
_HIGH_AUTHORITY = {"OFFICIAL", "DIRECT_OBSERVATION", "REPORTED"}
_DOMAIN_BY_STATE: dict[str, ClaimDomain] = {
    "availability": "availability",
    "starter_security": "role",
    "snap_share": "opportunity",
    "route_participation": "opportunity",
    "target_share": "opportunity",
    "carry_share": "opportunity",
    "goal_line_role": "opportunity",
    "third_down_role": "opportunity",
    "role_security": "role",
    "travel_environment": "environment",
    "weather_environment": "environment",
}


def _utc(value: datetime | str | pd.Timestamp) -> datetime:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("timestamp is missing")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record_digest(payload: Mapping[str, object]) -> str:
    clean = dict(payload)
    clean.pop("content_sha256", None)
    return _sha256(_canonical_json(clean))


class ClaimProvenance(BaseModel):
    """Point-in-time provenance required for every structured football claim."""

    source_url: str
    publisher_type: str
    evidence_class: AuthorityClass
    authored_at_utc: datetime
    collected_at_utc: datetime
    available_at_utc: datetime
    availability_basis: AvailabilityBasis
    supporting_evidence: str
    extractor_version: str
    extractor_confidence: float = Field(ge=0.0, le=1.0)
    source_reliability: float = Field(ge=0.0, le=1.0)
    document_id: str | None = None
    content_hash: str | None = None
    caveats: list[str] = Field(default_factory=list)

    @field_validator("source_url", "publisher_type", "supporting_evidence", "extractor_version")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        cleaned = " ".join(str(value).split())
        if not cleaned:
            raise ValueError("provenance text fields cannot be empty")
        return cleaned

    @field_validator("authored_at_utc", "collected_at_utc", "available_at_utc", mode="before")
    @classmethod
    def normalize_timestamp(cls, value: object) -> datetime:
        if value is None:
            raise ValueError("claim provenance timestamps are required")
        return _utc(value)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def validate_temporal_order(self) -> ClaimProvenance:
        if self.authored_at_utc > self.collected_at_utc:
            raise ValueError("authored_at_utc cannot be after collected_at_utc")
        expected = (
            self.authored_at_utc
            if self.availability_basis == "published"
            else self.collected_at_utc
        )
        if self.available_at_utc != expected:
            raise ValueError(
                "available_at_utc must match the explicitly selected availability_basis"
            )
        return self


class StructuredClaim(BaseModel):
    """Canonical, source-preserving intelligence claim.

    This record is evidence, not a production feature. Conflicting records are preserved and
    resolved only into explicit disagreement diagnostics at an as-of cutoff.
    """

    claim_id: str
    player_id: str
    claim_type: str
    domain: ClaimDomain
    latent_state: str
    direction: float = Field(ge=-1.0, le=1.0)
    magnitude: float = Field(ge=0.0, le=1.0)
    status: ClaimStatus = "asserted"
    decay_half_life_days: float = Field(default=7.0, gt=0.0)
    provenance: ClaimProvenance
    supersedes_claim_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    content_sha256: str | None = None

    @field_validator("claim_id", "player_id", "claim_type", "latent_state")
    @classmethod
    def identifiers_nonempty(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("claim identifiers cannot be empty")
        return cleaned

    @model_validator(mode="after")
    def validate_status_linkage(self) -> StructuredClaim:
        if self.status in {"retracted", "superseded"} and not self.supersedes_claim_id:
            raise ValueError(f"{self.status} claims must reference supersedes_claim_id")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        digest = _sha256(_canonical_json(payload))
        if self.content_sha256 is None:
            self.content_sha256 = digest
        elif self.content_sha256 != digest:
            raise ValueError("structured claim content_sha256 does not match canonical content")
        return self

    @property
    def available_at_utc(self) -> datetime:
        return self.provenance.available_at_utc

    @property
    def semantic_key(self) -> str:
        return f"{self.player_id}|{self.domain}|{self.latent_state}|{self.claim_type}"


def structured_claim_from_news(
    claim: NewsClaim,
    *,
    publisher_type: str | None = None,
    availability_basis: AvailabilityBasis = "collected",
    extractor_version: str = "news-rules-v1",
    content_hash: str | None = None,
    caveats: Iterable[str] = (),
) -> StructuredClaim:
    authored = _utc(claim.published_at_utc)
    collected = _utc(claim.collected_at_utc)
    available = authored if availability_basis == "published" else collected
    domain = _DOMAIN_BY_STATE.get(claim.latent_state, "role")
    provenance = ClaimProvenance(
        source_url=claim.source_url,
        publisher_type=publisher_type or str(claim.evidence_class).lower(),
        evidence_class=claim.evidence_class,
        authored_at_utc=authored,
        collected_at_utc=collected,
        available_at_utc=available,
        availability_basis=availability_basis,
        supporting_evidence=claim.evidence_text,
        extractor_version=extractor_version,
        extractor_confidence=claim.extractor_confidence,
        source_reliability=claim.source_reliability,
        document_id=claim.document_id,
        content_hash=content_hash,
        caveats=list(caveats),
    )
    stable_identity = {
        "player_id": claim.player_id,
        "claim_type": claim.claim_type,
        "latent_state": claim.latent_state,
        "document_id": claim.document_id,
        "source_url": claim.source_url,
        "authored_at_utc": authored.isoformat(),
        "evidence_text": claim.evidence_text,
    }
    return StructuredClaim(
        claim_id=_sha256(_canonical_json(stable_identity))[:32],
        player_id=claim.player_id,
        claim_type=claim.claim_type,
        domain=domain,
        latent_state=claim.latent_state,
        direction=claim.direction,
        magnitude=claim.magnitude,
        decay_half_life_days=claim.decay_half_life_days,
        provenance=provenance,
        metadata={"source_claim_id": claim.claim_id},
    )


class StructuredClaimLedger:
    """Write-once claim store with point-in-time queries and integrity verification."""

    def __init__(self, root: str | Path = "artifacts/structured_intelligence") -> None:
        self.root = Path(root)
        self.claim_root = self.root / "claims"

    def claim_path(self, claim_id: str) -> Path:
        safe = str(claim_id).strip()
        if not safe or "/" in safe or "\\" in safe:
            raise ValueError("invalid claim_id")
        return self.claim_root / safe[:2] / f"{safe}.json"

    @staticmethod
    def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    @staticmethod
    def _load(path: Path) -> StructuredClaim:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"structured claim is not a JSON object: {path}")
        claim = StructuredClaim.model_validate(payload)
        expected = str(payload.get("content_sha256") or "")
        actual = _record_digest(payload)
        if expected != actual:
            raise ValueError(
                f"structured claim integrity check failed for {claim.claim_id}: "
                f"expected {expected}, got {actual}"
            )
        return claim

    def save(self, claim: StructuredClaim) -> bool:
        payload = claim.model_dump(mode="json")
        if str(payload.get("content_sha256") or "") != _record_digest(payload):
            raise ValueError("structured claim digest is invalid before persistence")
        path = self.claim_path(claim.claim_id)
        if path.exists():
            existing = self._load(path)
            if existing.content_sha256 == claim.content_sha256:
                return False
            raise ValueError(f"immutable structured claim conflict for {claim.claim_id}")
        self._atomic_write(path, payload)
        return True

    def load(self, claim_id: str) -> StructuredClaim:
        path = self.claim_path(claim_id)
        if not path.is_file():
            raise FileNotFoundError(f"structured claim unavailable: {claim_id}")
        return self._load(path)

    def claims(
        self,
        *,
        as_of_utc: datetime | str | pd.Timestamp | None = None,
        player_id: str | None = None,
        domain: ClaimDomain | None = None,
    ) -> list[StructuredClaim]:
        if not self.claim_root.exists():
            return []
        cutoff = _utc(as_of_utc) if as_of_utc is not None else None
        rows: list[StructuredClaim] = []
        for path in sorted(self.claim_root.rglob("*.json")):
            claim = self._load(path)
            if cutoff is not None and claim.available_at_utc > cutoff:
                continue
            if player_id is not None and claim.player_id != str(player_id):
                continue
            if domain is not None and claim.domain != domain:
                continue
            rows.append(claim)
        return rows

    def health(self) -> dict[str, object]:
        failures: list[str] = []
        count = 0
        if self.claim_root.exists():
            for path in sorted(self.claim_root.rglob("*.json")):
                try:
                    self._load(path)
                    count += 1
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    failures.append(f"{path.as_posix()}:{exc}")
        return {
            "root": self.root.as_posix(),
            "claim_count": count,
            "integrity_verified": not failures,
            "integrity_failures": failures,
            "authority": "research_evidence_only",
        }


def build_state_evidence_snapshots(
    claims: Iterable[StructuredClaim],
    *,
    as_of_utc: datetime | str | pd.Timestamp,
) -> pd.DataFrame:
    """Resolve claims into transparent consensus + disagreement diagnostics.

    Opposing evidence is never discarded. `conflict_score` is zero when all weighted evidence has
    the same sign and reaches one when positive and negative support are equally balanced.
    """

    cutoff = _utc(as_of_utc)
    grouped: dict[tuple[str, str], list[StructuredClaim]] = defaultdict(list)
    for claim in claims:
        if claim.available_at_utc > cutoff:
            continue
        if claim.status != "asserted":
            continue
        grouped[(claim.player_id, claim.latent_state)].append(claim)

    rows: list[dict[str, object]] = []
    for (player_id, latent_state), state_claims in sorted(grouped.items()):
        weighted_sum = 0.0
        total_weight = 0.0
        positive_weight = 0.0
        negative_weight = 0.0
        sources: set[str] = set()
        classes: dict[str, int] = defaultdict(int)
        latest_available: datetime | None = None
        domains: set[str] = set()
        for claim in state_claims:
            age_days = max((cutoff - claim.available_at_utc).total_seconds() / 86400.0, 0.0)
            recency = math.exp(
                -math.log(2.0) * age_days / max(float(claim.decay_half_life_days), 1e-6)
            )
            authority = _AUTHORITY_WEIGHT[str(claim.provenance.evidence_class)]
            weight = (
                recency
                * claim.provenance.extractor_confidence
                * claim.provenance.source_reliability
                * authority
            )
            signed_value = claim.direction * claim.magnitude
            weighted_sum += signed_value * weight
            total_weight += weight
            if signed_value > 0:
                positive_weight += weight * abs(signed_value)
            elif signed_value < 0:
                negative_weight += weight * abs(signed_value)
            sources.add(claim.provenance.source_url)
            classes[str(claim.provenance.evidence_class)] += 1
            domains.add(claim.domain)
            if latest_available is None or claim.available_at_utc > latest_available:
                latest_available = claim.available_at_utc

        opposing_total = positive_weight + negative_weight
        conflict_score = (
            2.0 * min(positive_weight, negative_weight) / opposing_total
            if opposing_total > 0.0
            else 0.0
        )
        consensus = weighted_sum / total_weight if total_weight > 0.0 else 0.0
        diversity = min(len(sources) / 3.0, 1.0)
        support_strength = min(1.0 - math.exp(-total_weight), 1.0) * (0.5 + 0.5 * diversity)
        high_authority_count = sum(classes[name] for name in _HIGH_AUTHORITY)
        rows.append(
            {
                "player_id": player_id,
                "latent_state": latent_state,
                "domains": sorted(domains),
                "as_of_utc": cutoff,
                "latest_available_at_utc": latest_available,
                "claim_count": len(state_claims),
                "source_count": len(sources),
                "high_authority_claim_count": high_authority_count,
                "speculation_claim_count": classes["SPECULATION"],
                "consensus_signal": float(max(-1.0, min(consensus, 1.0))),
                "support_strength": float(max(0.0, min(support_strength, 1.0))),
                "conflict_score": float(max(0.0, min(conflict_score, 1.0))),
                "positive_support": float(positive_weight),
                "negative_support": float(negative_weight),
                "production_feature_enabled": False,
                "authority": "research_evidence_only",
            }
        )
    return pd.DataFrame(rows)
