from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from player_state_engine.data.io import write_table
from player_state_engine.intelligence.activation import IntelligenceActivationRegistry
from player_state_engine.intelligence.io import load_documents_jsonl
from player_state_engine.intelligence.news import extract_news_claims
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build an immutable structured-intelligence claim ledger and point-in-time research "
            "evidence snapshot from archived public documents."
        )
    )
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--as-of", required=True, help="UTC-aware ISO-8601 evidence cutoff")
    parser.add_argument(
        "--availability-basis",
        choices=("collected", "published"),
        default="collected",
        help=(
            "When a claim becomes usable. 'collected' is the conservative live default; "
            "'published' must be an explicit historical-replay choice."
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

    if not args.documents.is_file():
        raise FileNotFoundError(f"document archive unavailable: {args.documents}")

    as_of = _utc_iso(args.as_of)
    documents = load_documents_jsonl(args.documents)
    news_claims = extract_news_claims(documents)
    document_hash_by_id = {
        document.document_id: document.content_hash for document in documents
    }
    document_platform_by_id = {
        document.document_id: str(document.platform) for document in documents
    }

    structured_claims = [
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
    snapshot_path = snapshot_dir / f"structured_news_{as_of.replace(':', '').replace('+', '_')}.parquet"
    write_table(snapshot, snapshot_path)

    registry = (
        IntelligenceActivationRegistry.load(args.activation_registry)
        if args.activation_registry is not None
        else IntelligenceActivationRegistry()
    )
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "as_of_utc": as_of,
        "availability_basis": args.availability_basis,
        "authority": "research_evidence_only",
        "automatic_promotion": False,
        "input": {
            "path": args.documents.as_posix(),
            "sha256": _sha256(args.documents),
            "document_count": len(documents),
        },
        "claims": {
            "extracted": len(news_claims),
            "canonical": len(structured_claims),
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
