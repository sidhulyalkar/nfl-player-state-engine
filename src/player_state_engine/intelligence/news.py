from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from player_state_engine.intelligence.schemas import PublicDocument

ClaimType = Literal[
    "workload_limit",
    "starter_role",
    "backup_role",
    "committee_role",
    "increased_routes",
    "increased_targets",
    "coach_role_change",
    "travel_complication",
    "weather_complication",
]


class NewsClaim(BaseModel):
    claim_id: str
    player_id: str
    claim_type: ClaimType
    direction: float = Field(ge=-1.0, le=1.0)
    magnitude: float = Field(ge=0.0, le=1.0)
    source_url: str
    published_at_utc: datetime
    collected_at_utc: datetime
    evidence_text: str
    extractor_confidence: float = Field(ge=0.0, le=1.0)
    source_reliability: float = Field(ge=0.0, le=1.0)
    document_id: str


_PATTERNS: dict[ClaimType, tuple[tuple[str, float], ...]] = {
    "workload_limit": (
        (
            r"\b(?:limited|pitch count|snap count|ease(?:d)? (?:him|them) in|not (?:have )?(?:a )?full workload)\b",
            -1.0,
        ),
    ),
    "starter_role": (
        (r"\b(?:will start|named (?:the )?starter|starting role|remain(?:s)? the starter)\b", 1.0),
    ),
    "backup_role": ((r"\b(?:backup role|second[- ]string|will back up|reserve role)\b", -0.65),),
    "committee_role": (
        (r"\b(?:committee|split carries|share touches|hot hand|rotation)\b", -0.35),
    ),
    "increased_routes": (
        (r"\b(?:more routes|route participation|expanded route|run more routes)\b", 0.6),
    ),
    "increased_targets": (
        (r"\b(?:more targets|target share|feature(?:d)? in the passing game|more looks)\b", 0.65),
    ),
    "coach_role_change": (
        (
            r"\b(?:role (?:will|is expected to) (?:grow|expand|change)|bigger role|reduced role|change in usage)\b",
            0.4,
        ),
    ),
    "travel_complication": (
        (r"\b(?:travel delay|flight delay|stranded|late arrival|travel complication)\b", -0.25),
    ),
    "weather_complication": (
        (r"\b(?:high winds?|heavy rain|snowstorm|extreme cold|weather concern)\b", -0.2),
    ),
}


def _excerpt(text: str, match: re.Match[str], radius: int = 140) -> str:
    start = max(match.start() - radius, 0)
    end = min(match.end() + radius, len(text))
    return " ".join(text[start:end].split())


def extract_news_claims(
    documents: Iterable[PublicDocument],
    *,
    source_reliability: dict[str, float] | None = None,
) -> list[NewsClaim]:
    """Extract conservative, timestamped football-role claims from public text."""

    reliability_map = source_reliability or {}
    claims: list[NewsClaim] = []
    for document in documents:
        published = document.authored_at_utc or document.collected_at_utc
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        reliability = float(
            reliability_map.get(
                document.platform, document.metadata.get("source_reliability", 0.65)
            )
        )
        for claim_type, patterns in _PATTERNS.items():
            for pattern, direction in patterns:
                match = re.search(pattern, document.text, flags=re.IGNORECASE)
                if not match:
                    continue
                explicit_quote = bool(
                    re.search(
                        r"\b(?:coach|head coach|offensive coordinator|said|told reporters)\b",
                        document.text,
                        re.I,
                    )
                )
                confidence = min(
                    0.55 + 0.2 * explicit_quote + 0.15 * (document.author_handle is not None), 0.95
                )
                magnitude = min(abs(direction), 1.0)
                claim_id = f"{document.document_id}:{claim_type}:{match.start()}"
                claims.append(
                    NewsClaim(
                        claim_id=claim_id,
                        player_id=document.player_id,
                        claim_type=claim_type,
                        direction=direction,
                        magnitude=magnitude,
                        source_url=document.source_url,
                        published_at_utc=published,
                        collected_at_utc=document.collected_at_utc,
                        evidence_text=_excerpt(document.text, match),
                        extractor_confidence=confidence,
                        source_reliability=max(0.0, min(reliability, 1.0)),
                        document_id=document.document_id,
                    )
                )
                break
    return claims


def claims_to_feature_snapshots(
    claims: Iterable[NewsClaim],
    *,
    half_life_days: float = 7.0,
) -> pd.DataFrame:
    """Aggregate claims into cumulative player snapshots with full provenance retained separately."""

    grouped: dict[str, list[NewsClaim]] = defaultdict(list)
    for claim in claims:
        grouped[claim.player_id].append(claim)
    rows: list[dict[str, object]] = []
    for player_id, player_claims in grouped.items():
        ordered = sorted(player_claims, key=lambda c: c.published_at_utc)
        history: list[NewsClaim] = []
        for claim in ordered:
            history.append(claim)
            as_of = claim.published_at_utc
            scores = {name: 0.0 for name in _PATTERNS}
            weights = {name: 0.0 for name in _PATTERNS}
            sources: set[str] = set()
            for item in history:
                age_days = max((as_of - item.published_at_utc).total_seconds() / 86400.0, 0.0)
                recency = math.exp(-math.log(2.0) * age_days / half_life_days)
                weight = recency * item.extractor_confidence * item.source_reliability
                scores[item.claim_type] += item.direction * item.magnitude * weight
                weights[item.claim_type] += weight
                sources.add(item.source_url)
            normalized = {
                name: scores[name] / max(weights[name], 1e-9) if weights[name] else 0.0
                for name in scores
            }
            rows.append(
                {
                    "player_id": player_id,
                    "as_of_utc": as_of,
                    **{f"news_{name}": value for name, value in normalized.items()},
                    "news_claim_count": len(history),
                    "news_source_count": len(sources),
                    "news_evidence_strength": min(len(history) / 8.0, 1.0)
                    * min(len(sources) / 3.0, 1.0),
                }
            )
    return (
        pd.DataFrame(rows).sort_values(["player_id", "as_of_utc"]).reset_index(drop=True)
        if rows
        else pd.DataFrame()
    )


def claims_to_evidence_frame(claims: Iterable[NewsClaim]) -> pd.DataFrame:
    return pd.DataFrame([claim.model_dump(mode="json") for claim in claims])
