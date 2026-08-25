from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from player_state_engine.intelligence.activation import IntelligenceActivationRegistry
from player_state_engine.intelligence.structured import (
    ClaimDomain,
    StructuredClaim,
    StructuredClaimLedger,
    build_state_evidence_snapshots,
    effective_claims_as_of,
)


def _utc(value: datetime | str | pd.Timestamp | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("as_of timestamp is missing")
    if timestamp.tzinfo is None:
        raise ValueError("as_of timestamp must include a timezone")
    return timestamp.tz_convert("UTC").to_pydatetime()


def _filter_domain(
    claims: list[StructuredClaim],
    domain: ClaimDomain | None,
) -> list[StructuredClaim]:
    if domain is None:
        return claims
    return [claim for claim in claims if claim.domain == domain]


class StructuredIntelligenceArtifactStore:
    """Read-only product adapter over the immutable structured-intelligence evidence ledger."""

    def __init__(
        self,
        root: str | Path = "artifacts/structured_intelligence",
        *,
        activation_registry_path: str | Path = "config/intelligence_activation.json",
    ) -> None:
        self.root = Path(root)
        self.ledger = StructuredClaimLedger(self.root)
        self.activation_registry_path = Path(activation_registry_path)
        self.manifest_path = self.root / "run_manifest.json"

    def _activation(self) -> IntelligenceActivationRegistry:
        return IntelligenceActivationRegistry.load(self.activation_registry_path)

    def _manifest(self) -> dict[str, object] | None:
        if not self.manifest_path.is_file():
            return None
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("structured-intelligence run manifest is not a JSON object")
        return payload

    def health(self) -> dict[str, object]:
        ledger = self.ledger.health()
        manifest_error: str | None = None
        manifest: dict[str, object] | None = None
        try:
            manifest = self._manifest()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            manifest_error = str(exc)
        activation_error: str | None = None
        try:
            activation = self._activation().summary()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            activation_error = str(exc)
            activation = None
        failures = list(ledger.get("integrity_failures") or [])
        if manifest_error:
            failures.append(f"manifest:{manifest_error}")
        if activation_error:
            failures.append(f"activation_registry:{activation_error}")
        return {
            "root": self.root.as_posix(),
            "integrity_verified": not failures,
            "integrity_failures": failures,
            "claim_count": int(ledger.get("claim_count", 0)),
            "manifest_available": manifest is not None,
            "manifest": manifest,
            "activation": activation,
            "authority": "research_evidence_only",
            "automatic_promotion": False,
        }

    def snapshot(
        self,
        *,
        as_of_utc: datetime | str | pd.Timestamp | None = None,
        player_id: str | None = None,
        domain: ClaimDomain | None = None,
    ) -> dict[str, object]:
        as_of = _utc(as_of_utc)
        health = self.health()
        if not health["integrity_verified"]:
            return {
                "data_mode": "UNAVAILABLE",
                "authority": "research_evidence_only",
                "automatic_promotion": False,
                "as_of_utc": as_of.isoformat(),
                "health": health,
                "reason": "structured_intelligence_integrity_failure",
                "states": [],
            }

        all_claims = self.ledger.claims(as_of_utc=as_of, player_id=player_id)
        visible_claims = _filter_domain(all_claims, domain)
        effective_claims = effective_claims_as_of(all_claims, as_of_utc=as_of)
        visible_effective_claims = _filter_domain(effective_claims, domain)
        states = build_state_evidence_snapshots(visible_effective_claims, as_of_utc=as_of)
        records = (
            json.loads(states.to_json(orient="records", date_format="iso"))
            if not states.empty
            else []
        )
        conflict_values = (
            pd.to_numeric(states["conflict_score"], errors="coerce")
            if "conflict_score" in states
            else pd.Series(dtype=float)
        )
        return {
            "data_mode": "STRUCTURED_EVIDENCE" if visible_claims else "UNAVAILABLE",
            "authority": "research_evidence_only",
            "automatic_promotion": False,
            "as_of_utc": as_of.isoformat(),
            "filters": {"player_id": player_id, "domain": domain},
            "health": health,
            "activation": health.get("activation"),
            "claim_count": len(visible_claims),
            "effective_claim_count": len(visible_effective_claims),
            "state_count": len(records),
            "summary": {
                "mean_conflict_score": (
                    float(conflict_values.mean()) if len(conflict_values) else None
                ),
                "max_conflict_score": (
                    float(conflict_values.max()) if len(conflict_values) else None
                ),
                "states_with_conflict": (
                    int((conflict_values > 0.0).sum()) if len(conflict_values) else 0
                ),
                "production_feature_enabled": False,
            },
            "states": records,
        }

    def claims_snapshot(
        self,
        *,
        as_of_utc: datetime | str | pd.Timestamp | None = None,
        player_id: str | None = None,
        domain: ClaimDomain | None = None,
        limit: int = 200,
    ) -> dict[str, object]:
        as_of = _utc(as_of_utc)
        health = self.health()
        if not health["integrity_verified"]:
            return {
                "data_mode": "UNAVAILABLE",
                "authority": "research_evidence_only",
                "as_of_utc": as_of.isoformat(),
                "health": health,
                "claims": [],
            }

        all_claims = self.ledger.claims(as_of_utc=as_of, player_id=player_id)
        visible_claims = _filter_domain(all_claims, domain)
        ordered = sorted(
            visible_claims,
            key=lambda claim: (claim.available_at_utc, claim.claim_id),
            reverse=True,
        )
        effective_ids = {
            claim.claim_id for claim in effective_claims_as_of(all_claims, as_of_utc=as_of)
        }
        records = []
        for claim in ordered[:limit]:
            record = claim.model_dump(mode="json")
            record["effective_at_cutoff"] = claim.claim_id in effective_ids
            records.append(record)
        return {
            "data_mode": "STRUCTURED_EVIDENCE" if visible_claims else "UNAVAILABLE",
            "authority": "research_evidence_only",
            "automatic_promotion": False,
            "as_of_utc": as_of.isoformat(),
            "filters": {"player_id": player_id, "domain": domain},
            "total_matches": len(visible_claims),
            "returned": len(records),
            "health": health,
            "claims": records,
        }
