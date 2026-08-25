from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from player_state_engine.data.io import read_table, write_table
from player_state_engine.intelligence.activation import IntelligenceActivationRegistry
from player_state_engine.intelligence.availability import OfficialAvailabilityEvidence
from player_state_engine.intelligence.io import load_documents_jsonl
from player_state_engine.intelligence.news import extract_news_claims
from player_state_engine.intelligence.official_claims import canonicalize_official_availability
from player_state_engine.intelligence.structured import (
    StructuredClaimLedger,
    build_state_evidence_snapshots,
    structured_claim_from_news,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_iso(value: str) -> str:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("--as-of must include a timezone")
    return timestamp.astimezone(UTC).isoformat()


def _load_official_evidence(path: Path | None) -> list[OfficialAvailabilityEvidence]:
    if path is None:
        return []
    if not path.is_file():
        raise FileNotFoundError(f"official evidence unavailable: {path}")
    frame = read_table(path)
    records = frame.where(pd.notna(frame), None).to_dict(orient="records")
    return [OfficialAvailabilityEvidence.model_validate(record) for record in records]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build an immutable structured-intelligence claim ledger and point-in-time research "
            "evidence snapshot from archived official and/or public documents."
        )
    )
    parser.add_argument(
        "--documents",
        type=Path,
        default=None,
        help="Optional archived PublicDocument JSONL for structured-news extraction.",
    )
    parser.add_argument(
        "--official-evidence",
        type=Path,
        default=None,
        help="Optional CSV/Parquet of normalized OfficialAvailabilityEvidence rows.",
    )
    parser.add_argument("--as-of", required=True, help="UTC-aware ISO-8601 evidence cutoff")
    parser.add_argument(
        "--availability-basis",
        choices=("collected", "published"),
        default="collected",
        help=(
            "When public-document claims become usable. 'collected' is the conservative live "
            "default; 'published' must be an explicit historical-replay choice. Official evidence "
            "always uses its normalized observed_at timestamp."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/structured_intelligence"),
    )
    parser.add_argument(
        "--activation-registry",
        type=Path,
        default=None,
        help="Optional activation registry to report. This command never promotes a family.",
    )
    args = parser.parse_args()

    if args.documents is None and args.official_evidence is None:
        raise ValueError("at least one of --documents or --official-evidence is required")
    if args.documents is not None and not args.documents.is_file():
        raise FileNotFoundError(f"document archive unavailable: {args.documents}")

    as_of = _utc_iso(args.as_of)

    documents = load_documents_jsonl(args.documents) if args.documents is not None else []
    news_claims = extract_news_claims(documents)
    document_hash_by_id = {
        document.document_id: document.content_hash for document in documents
    }
    document_platform_by_id = {
        document.document_id: str(document.platform) for document in documents
    }
    structured_news_claims = [
        structured_claim_from_news(
            claim,
            publisher_type=document_platform_by_id.get(claim.document_id),
            availability_basis=args.availability_basis,
            content_hash=document_hash_by_id.get(claim.document_id),
            caveats=(
                "Structured extraction is evidence classification, not a calibrated forecast.",
                "This claim family remains subject to frozen ablation and negative controls.",
            ),
        )
        for claim in news_claims
    ]

    official_evidence = _load_official_evidence(args.official_evidence)
    official_claims = canonicalize_official_availability(official_evidence)
    structured_claims = [*official_claims, *structured_news_claims]

    ledger = StructuredClaimLedger(args.output_root)
    created = 0
    unchanged = 0
    for claim in structured_claims:
        if ledger.save(claim):
            created += 1
        else:
            unchanged += 1

    eligible = ledger.claims(as_of_utc=as_of)
    snapshot = build_state_evidence_snapshots(eligible, as_of_utc=as_of)
    snapshot_dir = args.output_root / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    safe_cutoff = as_of.replace(":", "").replace("+", "_")
    snapshot_path = snapshot_dir / f"structured_intelligence_{safe_cutoff}.parquet"
    write_table(snapshot, snapshot_path)

    registry = (
        IntelligenceActivationRegistry.load(args.activation_registry)
        if args.activation_registry is not None
        else IntelligenceActivationRegistry()
    )
    inputs: dict[str, object] = {}
    if args.documents is not None:
        inputs["public_documents"] = {
            "path": args.documents.as_posix(),
            "sha256": _sha256(args.documents),
            "document_count": len(documents),
            "availability_basis": args.availability_basis,
        }
    if args.official_evidence is not None:
        inputs["official_availability"] = {
            "path": args.official_evidence.as_posix(),
            "sha256": _sha256(args.official_evidence),
            "evidence_count": len(official_evidence),
            "availability_basis": "observed_at_utc",
        }

    manifest = {
        "schema_version": 2,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "as_of_utc": as_of,
        "authority": "research_evidence_only",
        "automatic_promotion": False,
        "inputs": inputs,
        "claims": {
            "news_extracted": len(news_claims),
            "news_canonical": len(structured_news_claims),
            "official_evidence": len(official_evidence),
            "official_canonical": len(official_claims),
            "canonical_total": len(structured_claims),
            "created": created,
            "unchanged": unchanged,
            "eligible_at_cutoff": len(eligible),
        },
        "snapshot": {
            "path": snapshot_path.as_posix(),
            "rows": len(snapshot),
        },
        "ledger_health": ledger.health(),
        "activation": registry.summary(),
        "note": (
            "The operator creates research evidence only. Intelligence features remain disabled "
            "unless a separately reviewed activation registry explicitly enables the family."
        ),
    }
    manifest_path = args.output_root / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
