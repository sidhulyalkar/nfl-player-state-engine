from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Platform = Literal[
    "public_web", "public_browser", "rss", "x", "threads", "instagram", "tiktok", "manual"
]


class PlayerSource(BaseModel):
    player_id: str
    player_name: str | None = None
    platform: Platform
    handle: str | None = None
    url: str | None = None
    enabled: bool = True
    notes: str | None = None


class PublicDocument(BaseModel):
    document_id: str
    player_id: str
    player_name: str | None = None
    platform: Platform
    source_url: str
    text: str
    title: str | None = None
    author_handle: str | None = None
    authored_at_utc: datetime | None = None
    collected_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    engagement: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str | None = None

    @field_validator("text")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Document text cannot be empty.")
        return cleaned

    def model_post_init(self, __context: Any) -> None:
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class PersonaEvidence(BaseModel):
    document_id: str
    signal: str
    score: float
    excerpt: str
    authored_at_utc: datetime | None = None


class PersonaSnapshot(BaseModel):
    """Auditable public-context features, not a psychological diagnosis."""

    player_id: str
    as_of_utc: datetime
    document_count: int
    source_count: int
    lookback_days: int
    persona_training_focus: float = 0.0
    persona_recovery_focus: float = 0.0
    persona_competitive_language: float = 0.0
    persona_team_orientation: float = 0.0
    persona_leadership_language: float = 0.0
    persona_matchup_specificity: float = 0.0
    persona_role_expectation: float = 0.0
    persona_media_visibility: float = 0.0
    persona_commercial_content_share: float = 0.0
    persona_evidence_strength: float = 0.0
    evidence: list[PersonaEvidence] = Field(default_factory=list)
    extractor_version: str = "rules-v1"
    caveats: list[str] = Field(
        default_factory=lambda: [
            "Public posts are selective performances, not direct measurements of private personality.",
            "Features must remain secondary and earn inclusion through timestamped ablation tests.",
        ]
    )
