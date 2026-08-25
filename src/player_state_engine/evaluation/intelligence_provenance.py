from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from player_state_engine.state_graph.experiments import EvidenceTier


class IntelligenceEvidenceProvenance(BaseModel):
    """Authority metadata for a frozen intelligence-evidence sample.

    A provenance record can describe synthetic or unverified research, but Tier-2+
    evidence requires an immutable sample identity and explicit confirmation that both
    evidence and source-coverage observations respect the historical prediction cutoff.
    """

    schema_version: int = Field(default=1, ge=1)
    authority: Literal["research_evidence_only"] = "research_evidence_only"
    evidence_tier: int = Field(default=int(EvidenceTier.SYNTHETIC_ONLY), ge=0, le=5)
    frozen_sample_id: str | None = None
    point_in_time_verified: bool = False
    source_coverage_point_in_time_verified: bool = False
    description: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("frozen_sample_id", "description", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(str(value).split())
        return cleaned or None

    @field_validator("evidence_tier")
    @classmethod
    def validate_tier(cls, value: int) -> int:
        try:
            EvidenceTier(int(value))
        except ValueError as exc:
            raise ValueError(f"unsupported evidence tier: {value}") from exc
        return int(value)

    @model_validator(mode="after")
    def validate_frozen_authority(self) -> IntelligenceEvidenceProvenance:
        if self.tier >= EvidenceTier.MULTI_SEASON_ISOLATED:
            missing: list[str] = []
            if not self.frozen_sample_id:
                missing.append("frozen_sample_id")
            if not self.point_in_time_verified:
                missing.append("point_in_time_verified")
            if not self.source_coverage_point_in_time_verified:
                missing.append("source_coverage_point_in_time_verified")
            if missing:
                raise ValueError(
                    "Tier-2+ intelligence evidence requires frozen point-in-time provenance: "
                    + ", ".join(missing)
                )
        return self

    @property
    def tier(self) -> EvidenceTier:
        return EvidenceTier(int(self.evidence_tier))

    @classmethod
    def synthetic_default(cls) -> IntelligenceEvidenceProvenance:
        return cls(
            evidence_tier=int(EvidenceTier.SYNTHETIC_ONLY),
            frozen_sample_id=None,
            point_in_time_verified=False,
            source_coverage_point_in_time_verified=False,
            description="No evidence provenance manifest supplied; fail closed to synthetic-only.",
        )

    @classmethod
    def load(cls, path: str | Path) -> IntelligenceEvidenceProvenance:
        location = Path(path)
        payload = json.loads(location.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("intelligence evidence provenance must be a JSON object")
        return cls.model_validate(payload)
