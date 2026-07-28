from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime

import pandas as pd

from player_state_engine.intelligence.schemas import (
    PersonaEvidence,
    PersonaSnapshot,
    PublicDocument,
)

SIGNAL_PATTERNS: dict[str, tuple[str, ...]] = {
    "training_focus": (
        r"\btrain(?:ing|ed)?\b",
        r"\bworkout\b",
        r"\bfilm study\b",
        r"\bpractice\b",
        r"\boffseason\b",
        r"\bgrind\b",
        r"\breps?\b",
    ),
    "recovery_focus": (
        r"\brecover(?:y|ing|ed)?\b",
        r"\brehab\b",
        r"\btherapy\b",
        r"\btreatment\b",
        r"\brest\b",
        r"\bhealthy\b",
        r"\breturn\b",
    ),
    "competitive_language": (
        r"\bwin(?:ning)?\b",
        r"\bcompete\b",
        r"\bdominate\b",
        r"\bprove\b",
        r"\bchallenge\b",
        r"\bchampion\b",
        r"\bbet on me\b",
    ),
    "team_orientation": (
        r"\bteam\b",
        r"\bteammates?\b",
        r"\bbrothers?\b",
        r"\btogether\b",
        r"\bwe\b",
        r"\bour\b",
        r"\bunit\b",
    ),
    "leadership_language": (
        r"\blead(?:er|ership|ing)?\b",
        r"\baccountab(?:le|ility)\b",
        r"\bset the tone\b",
        r"\bveteran\b",
        r"\bmentor\b",
        r"\bexample\b",
    ),
    "matchup_specificity": (
        r"\bmatchup\b",
        r"\bdefense\b",
        r"\bcoverage\b",
        r"\bsecondary\b",
        r"\bfront seven\b",
        r"\bgame plan\b",
        r"\bopponent\b",
    ),
    "role_expectation": (
        r"\brole\b",
        r"\btargets?\b",
        r"\btouches\b",
        r"\bsnaps?\b",
        r"\bstarter\b",
        r"\bfeatured\b",
        r"\bopportunity\b",
        r"\bready when\b",
    ),
    "commercial_content": (
        r"\bpartner(?:ship)?\b",
        r"\bsponsored\b",
        r"\bad\b",
        r"\bpromo\b",
        r"\bdiscount code\b",
        r"\bshop now\b",
    ),
}


def _recency_weight(
    document: PublicDocument, as_of: datetime, half_life_days: float = 30.0
) -> float:
    timestamp = document.authored_at_utc or document.collected_at_utc
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    age_days = max((as_of - timestamp).total_seconds() / 86_400.0, 0.0)
    return float(math.exp(-math.log(2.0) * age_days / half_life_days))


def _score_document(text: str, patterns: tuple[str, ...]) -> tuple[float, str | None]:
    lowered = text.lower()
    matches = [pattern for pattern in patterns if re.search(pattern, lowered)]
    score = min(len(matches) / 3.0, 1.0)
    excerpt = None
    if matches:
        match = re.search(matches[0], lowered)
        if match:
            start = max(0, match.start() - 90)
            end = min(len(text), match.end() + 140)
            excerpt = text[start:end].strip()
    return score, excerpt


def build_persona_snapshots(
    documents: Iterable[PublicDocument],
    as_of_utc: datetime | None = None,
    lookback_days: int = 120,
    evidence_limit: int = 20,
) -> list[PersonaSnapshot]:
    """Create conservative, auditable public-context summaries from player-authored text."""

    as_of = as_of_utc or datetime.now(UTC)
    cutoff = as_of.timestamp() - lookback_days * 86_400
    grouped: dict[str, list[PublicDocument]] = defaultdict(list)
    for document in documents:
        timestamp = document.authored_at_utc or document.collected_at_utc
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        if timestamp.timestamp() <= as_of.timestamp() and timestamp.timestamp() >= cutoff:
            grouped[document.player_id].append(document)

    snapshots: list[PersonaSnapshot] = []
    for player_id, player_documents in grouped.items():
        weighted_scores = {name: 0.0 for name in SIGNAL_PATTERNS}
        total_weight = 0.0
        evidence: list[PersonaEvidence] = []
        for document in player_documents:
            weight = _recency_weight(document, as_of)
            total_weight += weight
            for signal, patterns in SIGNAL_PATTERNS.items():
                raw_score, excerpt = _score_document(document.text, patterns)
                weighted = raw_score * weight
                weighted_scores[signal] += weighted
                if weighted > 0 and excerpt:
                    evidence.append(
                        PersonaEvidence(
                            document_id=document.document_id,
                            signal=signal,
                            score=weighted,
                            excerpt=excerpt,
                            authored_at_utc=document.authored_at_utc,
                        )
                    )
        denominator = max(total_weight, 1e-9)
        normalized = {
            name: min(score / denominator, 1.0) for name, score in weighted_scores.items()
        }
        visibility = min(math.log1p(len(player_documents)) / math.log(21), 1.0)
        evidence_strength = min(len(player_documents) / 20.0, 1.0) * min(
            len({d.platform for d in player_documents}) / 3.0, 1.0
        )
        evidence = sorted(evidence, key=lambda item: item.score, reverse=True)[:evidence_limit]
        snapshots.append(
            PersonaSnapshot(
                player_id=player_id,
                as_of_utc=as_of,
                document_count=len(player_documents),
                source_count=len({document.platform for document in player_documents}),
                lookback_days=lookback_days,
                persona_training_focus=normalized["training_focus"],
                persona_recovery_focus=normalized["recovery_focus"],
                persona_competitive_language=normalized["competitive_language"],
                persona_team_orientation=normalized["team_orientation"],
                persona_leadership_language=normalized["leadership_language"],
                persona_matchup_specificity=normalized["matchup_specificity"],
                persona_role_expectation=normalized["role_expectation"],
                persona_media_visibility=visibility,
                persona_commercial_content_share=normalized["commercial_content"],
                persona_evidence_strength=evidence_strength,
                evidence=evidence,
            )
        )
    return snapshots


def snapshots_to_feature_frame(snapshots: Iterable[PersonaSnapshot]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for snapshot in snapshots:
        payload = snapshot.model_dump(mode="json", exclude={"evidence", "caveats"})
        rows.append(payload)
    return pd.DataFrame(rows)
