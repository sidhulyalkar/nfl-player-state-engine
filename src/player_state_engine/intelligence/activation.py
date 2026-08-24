from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, field_validator, model_validator

FeatureFamily = Literal[
    "official_availability",
    "objective_opportunity",
    "structured_news",
    "public_player_context",
]
ActivationStatus = Literal["disabled", "shadow", "enabled"]

_DEFAULT_FAMILIES: tuple[FeatureFamily, ...] = (
    "official_availability",
    "objective_opportunity",
    "structured_news",
    "public_player_context",
)


def _utc(value: datetime | str | pd.Timestamp) -> datetime:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("timestamp is missing")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


class FeatureActivation(BaseModel):
    family: FeatureFamily
    status: ActivationStatus = "disabled"
    evidence_tier: str | None = None
    experiment_id: str | None = None
    approved_by: str | None = None
    approved_at_utc: datetime | None = None
    note: str | None = None
    automatic_promotion: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("approved_at_utc", mode="before")
    @classmethod
    def normalize_approved_at(cls, value: object) -> datetime | None:
        return None if value is None else _utc(value)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def validate_activation_authority(self) -> FeatureActivation:
        if self.automatic_promotion:
            raise ValueError("intelligence feature families cannot be promoted automatically")
        if self.status == "enabled":
            required = {
                "experiment_id": self.experiment_id,
                "evidence_tier": self.evidence_tier,
                "approved_by": self.approved_by,
                "approved_at_utc": self.approved_at_utc,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(
                    "enabled intelligence family requires manual evidence metadata: "
                    + ", ".join(missing)
                )
        return self


class IntelligenceActivationRegistry:
    """Manual, fail-closed authority boundary for intelligence feature families."""

    def __init__(self, entries: list[FeatureActivation] | None = None) -> None:
        supplied = entries or []
        by_family = {entry.family: entry for entry in supplied}
        self.entries: dict[FeatureFamily, FeatureActivation] = {
            family: by_family.get(family, FeatureActivation(family=family))
            for family in _DEFAULT_FAMILIES
        }

    @classmethod
    def load(cls, path: str | Path) -> IntelligenceActivationRegistry:
        location = Path(path)
        if not location.is_file():
            return cls()
        payload = json.loads(location.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("families"), list):
            raise ValueError("intelligence activation registry must contain a families list")
        entries = [FeatureActivation.model_validate(item) for item in payload["families"]]
        return cls(entries)

    def save(self, path: str | Path) -> Path:
        location = Path(path)
        location.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "automatic_promotion": False,
            "families": [
                self.entries[family].model_dump(mode="json") for family in _DEFAULT_FAMILIES
            ],
        }
        location.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return location

    def get(self, family: FeatureFamily) -> FeatureActivation:
        return self.entries[family]

    def is_enabled(self, family: FeatureFamily) -> bool:
        return self.get(family).status == "enabled"

    def require_enabled(self, family: FeatureFamily) -> FeatureActivation:
        activation = self.get(family)
        if activation.status != "enabled":
            raise RuntimeError(
                f"intelligence feature family {family!r} is {activation.status}; "
                "frozen evidence and explicit manual promotion are required before production use"
            )
        return activation

    def summary(self) -> dict[str, object]:
        return {
            "automatic_promotion": False,
            "families": {
                family: self.entries[family].model_dump(mode="json")
                for family in _DEFAULT_FAMILIES
            },
            "enabled": [family for family in _DEFAULT_FAMILIES if self.is_enabled(family)],
            "shadow": [
                family
                for family in _DEFAULT_FAMILIES
                if self.entries[family].status == "shadow"
            ],
            "disabled": [
                family
                for family in _DEFAULT_FAMILIES
                if self.entries[family].status == "disabled"
            ],
        }


def materialize_research_features(
    frame: pd.DataFrame,
    *,
    family: FeatureFamily,
    registry: IntelligenceActivationRegistry,
    feature_columns: list[str],
) -> pd.DataFrame:
    """Return intelligence model features only after the family clears the manual gate."""

    registry.require_enabled(family)
    required = {"player_id", *feature_columns}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"intelligence feature frame is missing columns: {sorted(missing)}")
    output = frame[["player_id", *feature_columns]].copy()
    output["intelligence_feature_family"] = family
    output["intelligence_feature_enabled"] = True
    return output
