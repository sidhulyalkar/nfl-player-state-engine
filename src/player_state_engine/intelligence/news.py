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

EvidenceClass = Literal[
    "OFFICIAL",
    "DIRECT_OBSERVATION",
    "REPORTED",
    "COACH_QUOTE",
    "PLAYER_QUOTE",
    "ANALYSIS",
    "SPECULATION",
]
LatentState = Literal[
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
]
ClaimType = Literal[
    "workload_limit",
    "practice_limit",
    "inactive",
    "return_to_practice",
    "starter_role",
    "backup_role",
    "committee_role",
    "first_team_reps",
    "depth_chart_promotion",
    "depth_chart_demotion",
    "goal_line_role",
    "third_down_role",
    "increased_routes",
    "increased_targets",
    "qb_starter_security",
    "coach_role_change",
    "travel_complication",
    "weather_complication",
]

_EVIDENCE_WEIGHT: dict[EvidenceClass, float] = {
    "OFFICIAL": 1.00,
    "DIRECT_OBSERVATION": 0.95,
    "REPORTED": 0.88,
    "COACH_QUOTE": 0.82,
    "PLAYER_QUOTE": 0.70,
    "ANALYSIS": 0.55,
    "SPECULATION": 0.30,
}

_CLAIM_STATE: dict[ClaimType, LatentState] = {
    "workload_limit": "snap_share",
    "practice_limit": "availability",
    "inactive": "availability",
    "return_to_practice": "availability",
    "starter_role": "starter_security",
    "backup_role": "starter_security",
    "committee_role": "carry_share",
    "first_team_reps": "starter_security",
    "depth_chart_promotion": "role_security",
    "depth_chart_demotion": "role_security",
    "goal_line_role": "goal_line_role",
    "third_down_role": "third_down_role",
    "increased_routes": "route_participation",
    "increased_targets": "target_share",
    "qb_starter_security": "starter_security",
    "coach_role_change": "role_security",
    "travel_complication": "travel_environment",
    "weather_complication": "weather_environment",
}

_CLAIM_HALF_LIFE: dict[ClaimType, float] = {
    "inactive": 2.0,
    "practice_limit": 3.0,
    "return_to_practice": 4.0,
    "travel_complication": 1.0,
    "weather_complication": 1.0,
    "first_team_reps": 5.0,
    "goal_line_role": 10.0,
    "third_down_role": 10.0,
    "increased_routes": 10.0,
    "increased_targets": 10.0,
    "starter_role": 14.0,
    "backup_role": 14.0,
    "qb_starter_security": 14.0,
}


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
    evidence_class: EvidenceClass = "ANALYSIS"
    latent_state: LatentState = "role_security"
    decay_half_life_days: float = Field(default=7.0, gt=0.0)


_PATTERNS: dict[ClaimType, tuple[tuple[str, float], ...]] = {
    "workload_limit": (
        (
            r"\b(?:limited workload|pitch count|snap count|ease(?:d)? (?:him|them) in|not (?:have )?(?:a )?full workload)\b",
            -1.0,
        ),
    ),
    "practice_limit": (
        (r"\b(?:limited participant|did not practice|dnp|held out of practice|practice limitation)\b", -0.8),
    ),
    "inactive": ((r"\b(?:ruled out|inactive|will not play|not expected to play)\b", -1.0),),
    "return_to_practice": (
        (r"\b(?:returned to practice|back at practice|full participant|cleared to practice)\b", 0.75),
    ),
    "starter_role": (
        (r"\b(?:will start|named (?:the )?starter|starting role|remain(?:s)? the starter)\b", 1.0),
    ),
    "backup_role": ((r"\b(?:backup role|second[- ]string|will back up|reserve role)\b", -0.65),),
    "committee_role": (
        (r"\b(?:committee|split carries|share touches|hot hand|rotation)\b", -0.35),
    ),
    "first_team_reps": (
        (r"\b(?:first[- ]team reps?|worked with the ones|ran with the starters|first[- ]team offense)\b", 0.75),
    ),
    "depth_chart_promotion": (
        (r"\b(?:moved up the depth chart|promoted to|now listed as (?:the )?(?:starter|no\. ?1|number one))\b", 0.75),
    ),
    "depth_chart_demotion": (
        (r"\b(?:moved down the depth chart|demoted|lost (?:the )?starting job|relegated to)\b", -0.8),
    ),
    "goal_line_role": (
        (r"\b(?:goal[- ]line back|goal[- ]line carries|short[- ]yardage role|red[- ]zone carries)\b", 0.65),
    ),
    "third_down_role": (
        (r"\b(?:third[- ]down back|two[- ]minute role|passing[- ]down role|third[- ]down snaps)\b", 0.65),
    ),
    "increased_routes": (
        (r"\b(?:more routes|route participation|expanded route|run more routes|route share)\b", 0.6),
    ),
    "increased_targets": (
        (r"\b(?:more targets|target share|feature(?:d)? in the passing game|more looks)\b", 0.65),
    ),
    "qb_starter_security": (
        (r"\b(?:starting quarterback|qb1|won the quarterback competition|will open the season as starter)\b", 0.9),
        (r"\b(?:quarterback competition remains open|could be benched|short leash at quarterback)\b", -0.55),
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


def _evidence_class(document: PublicDocument, excerpt: str) -> EvidenceClass:
    configured = str(document.metadata.get("evidence_class") or "").upper()
    if configured in _EVIDENCE_WEIGHT:
        return configured  # type: ignore[return-value]
    platform = str(document.platform).lower()
    source_type = str(document.metadata.get("source_type") or "").lower()
    if platform in {"nfl", "nfl_official", "team_official"} or source_type == "official":
        return "OFFICIAL"
    if re.search(r"\b(?:i saw|we observed|at practice|during team drills|11-on-11|7-on-7)\b", excerpt, re.I):
        return "DIRECT_OBSERVATION"
    if re.search(r"\b(?:head coach|coach|offensive coordinator)\b.{0,50}\b(?:said|told|expects?)\b", excerpt, re.I):
        return "COACH_QUOTE"
    if re.search(r"\b(?:the player|he|she|they)\b.{0,40}\b(?:said|told reporters)\b", excerpt, re.I):
        return "PLAYER_QUOTE"
    if re.search(r"\b(?:according to|reported by|reports? that|sources? say|league source)\b", excerpt, re.I):
        return "REPORTED"
    if re.search(r"\b(?:might|may|could|perhaps|possibly|would not be surprised|speculation)\b", excerpt, re.I):
        return "SPECULATION"
    return "ANALYSIS"


def extract_news_claims(
    documents: Iterable[PublicDocument],
    *,
    source_reliability: dict[str, float] | None = None,
) -> list[NewsClaim]:
    """Extract conservative, timestamped football-state claims from public text.

    This is evidence classification, not sentiment analysis. The same bullish sentence has very
    different model authority when it is an official status, direct practice observation, coach
    quote, reported fact or speculation.
    """
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
                excerpt = _excerpt(document.text, match)
                evidence_class = _evidence_class(document, excerpt)
                author_signal = 0.08 if document.author_handle is not None else 0.0
                confidence = min(
                    0.50 + 0.35 * _EVIDENCE_WEIGHT[evidence_class] + author_signal,
                    0.98,
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
                        evidence_text=excerpt,
                        extractor_confidence=confidence,
                        source_reliability=max(0.0, min(reliability, 1.0)),
                        document_id=document.document_id,
                        evidence_class=evidence_class,
                        latent_state=_CLAIM_STATE[claim_type],
                        decay_half_life_days=_CLAIM_HALF_LIFE.get(claim_type, 7.0),
                    )
                )
                break
    return claims


def claims_to_feature_snapshots(
    claims: Iterable[NewsClaim],
    *,
    half_life_days: float | None = None,
) -> pd.DataFrame:
    """Aggregate evidence into cumulative player state snapshots with source-aware decay."""
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
            state_scores: dict[str, float] = defaultdict(float)
            state_weights: dict[str, float] = defaultdict(float)
            class_counts: dict[str, int] = defaultdict(int)
            sources: set[str] = set()
            for item in history:
                age_days = max(
                    (as_of - item.published_at_utc).total_seconds() / 86400.0,
                    0.0,
                )
                half_life = half_life_days or item.decay_half_life_days
                recency = math.exp(-math.log(2.0) * age_days / max(half_life, 1e-6))
                evidence_weight = _EVIDENCE_WEIGHT[item.evidence_class]
                weight = (
                    recency
                    * item.extractor_confidence
                    * item.source_reliability
                    * evidence_weight
                )
                value = item.direction * item.magnitude
                scores[item.claim_type] += value * weight
                weights[item.claim_type] += weight
                state_scores[item.latent_state] += value * weight
                state_weights[item.latent_state] += weight
                class_counts[item.evidence_class] += 1
                sources.add(item.source_url)
            normalized = {
                name: scores[name] / max(weights[name], 1e-9) if weights[name] else 0.0
                for name in scores
            }
            states = {
                state: state_scores[state] / max(state_weights[state], 1e-9)
                for state in state_scores
            }
            high_authority = sum(
                class_counts[name]
                for name in ("OFFICIAL", "DIRECT_OBSERVATION", "REPORTED")
            )
            rows.append(
                {
                    "player_id": player_id,
                    "as_of_utc": as_of,
                    **{f"news_{name}": value for name, value in normalized.items()},
                    **{f"evidence_state_{state}": value for state, value in states.items()},
                    "news_claim_count": len(history),
                    "news_source_count": len(sources),
                    "news_high_authority_claim_count": high_authority,
                    "news_speculation_count": class_counts["SPECULATION"],
                    "news_evidence_strength": min(len(history) / 8.0, 1.0)
                    * min(len(sources) / 3.0, 1.0)
                    * min(0.5 + high_authority / 4.0, 1.0),
                }
            )
    return (
        pd.DataFrame(rows)
        .sort_values(["player_id", "as_of_utc"])
        .reset_index(drop=True)
        if rows
        else pd.DataFrame()
    )


def claims_to_evidence_frame(claims: Iterable[NewsClaim]) -> pd.DataFrame:
    return pd.DataFrame([claim.model_dump(mode="json") for claim in claims])
