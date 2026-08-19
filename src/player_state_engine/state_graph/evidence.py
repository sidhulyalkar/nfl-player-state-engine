from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

LatentTarget = Literal["availability", "participation", "opportunity", "execution", "environment"]

_ALLOWED_SOURCE_TARGETS: dict[str, set[LatentTarget]] = {
    "official_injury": {"availability"},
    "practice_report": {"availability", "participation"},
    "transactions": {"availability", "participation", "opportunity"},
    "depth_chart": {"participation", "opportunity"},
    "snap_counts": {"participation"},
    "routes_alignment": {"participation", "opportunity"},
    "structured_coach_claim": {"participation", "opportunity"},
    "structured_news_claim": {"availability", "participation", "opportunity", "environment"},
    "weather": {"environment"},
    "market_environment": {"environment"},
    "tracking_teacher": {"execution", "environment"},
}


@dataclass(slots=True, frozen=True)
class RoutedEvidence:
    player_id: str | None
    team: str | None
    source_family: str
    latent_target: LatentTarget
    signal_name: str
    value: float | str | bool
    confidence: float
    available_for_prediction_at: str


class LatentEvidenceRouter:
    """Prevent broad evidence families from becoming an un-auditable feature dump."""

    @staticmethod
    def allowed_targets(source_family: str) -> set[LatentTarget]:
        return set(_ALLOWED_SOURCE_TARGETS.get(str(source_family), set()))

    def route(self, claims: pd.DataFrame) -> list[RoutedEvidence]:
        required = {
            "source_family",
            "latent_target",
            "signal_name",
            "value",
            "confidence",
            "available_for_prediction_at",
        }
        missing = required - set(claims)
        if missing:
            raise ValueError(f"Evidence claims missing columns: {sorted(missing)}")
        routed: list[RoutedEvidence] = []
        for _, row in claims.iterrows():
            family = str(row["source_family"])
            target = str(row["latent_target"])
            if target not in self.allowed_targets(family):
                raise ValueError(
                    f"Source family {family!r} cannot update latent target {target!r}; "
                    "add an explicit research contract before using it."
                )
            routed.append(
                RoutedEvidence(
                    player_id=str(row["player_id"]) if "player_id" in row and pd.notna(row["player_id"]) else None,
                    team=str(row["team"]) if "team" in row and pd.notna(row["team"]) else None,
                    source_family=family,
                    latent_target=target,  # type: ignore[arg-type]
                    signal_name=str(row["signal_name"]),
                    value=row["value"],
                    confidence=float(max(0.0, min(1.0, float(row["confidence"])))),
                    available_for_prediction_at=str(row["available_for_prediction_at"]),
                )
            )
        return routed
