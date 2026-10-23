#!/usr/bin/env python3
"""Validate and compare independently generated XERJ/rg retrieval reports."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / ".xerj-reports"


def _read(path: Path) -> dict:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or not isinstance(report.get("results"), list):
        raise ValueError(f"Invalid retrieval report: {path}")
    return report


def compare(raw: dict, owner: dict, rg: dict) -> dict:
    identity = ("repo_commit", "source_fingerprint", "suite", "tasks", "k")
    for field in identity:
        values = [r.get(field) for r in (raw, owner, rg)]
        if any(value is None for value in values) or len(set(values)) != 1:
            raise ValueError(f"Incompatible benchmark reports: {field}")
    query_mode = raw.get("query_mode", "lexical")
    if query_mode != owner.get("query_mode", "lexical"):
        raise ValueError("Cannot compare different XERJ query modes")
    if raw.get("ranker") != "raw" or owner.get("ranker") != "symbol-owner":
        raise ValueError("Expected one raw and one symbol-owner XERJ report")
    if rg.get("kind") != "developer_retrieval_baseline":
        raise ValueError("Expected a separate local-code-search baseline")
    if raw.get("index_status") != "complete" or owner.get("index_status") != "complete":
        raise ValueError("Cannot qualify an incomplete XERJ index")
    if raw.get("unmapped_result_count") or owner.get("unmapped_result_count"):
        raise ValueError("Cannot qualify an index with unknown-source hits")
    if owner.get("ranked_hit_at_k") is None or owner.get("ranked_mrr_at_k") is None:
        raise ValueError("Symbol-owner report has no reranking measurements")

    def keyed(report: dict) -> dict:
        items = report["results"]
        ids = [item["id"] for item in items]
        if len(ids) != len(set(ids)) or len(ids) != report["tasks"]:
            raise ValueError("Duplicate or missing task identifiers")
        return {item["id"]: item for item in items}

    left, ranked, baseline = (keyed(r) for r in (raw, owner, rg))
    if left.keys() != ranked.keys() or left.keys() != baseline.keys():
        raise ValueError("Task IDs differ across benchmark modes")
    rows = []
    for case_id, a in left.items():
        b, c = ranked[case_id], baseline[case_id]
        if any(
            item["query"] != a["query"]
            or item["expected_paths"] != a["expected_paths"]
            for item in (b, c)
        ):
            raise ValueError(f"Query or answer labels changed across modes: {case_id}")
        raw_hit = bool(a["hit_at_k"])
        ranked_hit = bool(b["ranked_hit_at_k"])
        rg_hit = bool(c["hit_at_k"])
        rows.append({
            "id": case_id,
            "raw_hit": raw_hit,
            "owner_hit": ranked_hit,
            "rg_hit": rg_hit,
            "raw_rank": a["first_rank"],
            "owner_rank": b["ranked_first_rank"],
            "rg_rank": c["first_rank"],
            "owner_improves_hit": ranked_hit and not raw_hit,
            "owner_regresses_hit": raw_hit and not ranked_hit,
            "owner_beats_rg_hit": ranked_hit and not rg_hit,
            "rg_beats_owner_hit": rg_hit and not ranked_hit,
            "raw_top_k_invariant": (
                a["returned_paths"] == b["returned_paths"]
            ),
        })
    n = len(rows)
    def hit(key: str) -> float:
        return round(sum(row[key] for row in rows) / n, 4)
    gain = sum(row["owner_improves_hit"] for row in rows)
    loss = sum(row["owner_regresses_hit"] for row in rows)
    return {
        "schema_version": 1,
        "kind": "retrieval_navigation_comparison_only",
        "created_at": datetime.now(UTC).isoformat(),
        "repo_commit": raw["repo_commit"],
        "source_fingerprint": raw["source_fingerprint"],
        "suite": raw["suite"],
        "query_mode": query_mode,
        "tasks": n,
        "k": raw["k"],
        "raw_hit_at_k": hit("raw_hit"),
        "owner_hit_at_k": hit("owner_hit"),
        "rg_hit_at_k": hit("rg_hit"),
        "raw_mrr_at_k": raw["mrr_at_k"],
        "owner_mrr_at_k": owner["ranked_mrr_at_k"],
        "rg_mrr_at_k": rg["mrr_at_k"],
        "owner_hit_gains": gain,
        "owner_hit_regressions": loss,
        "candidate_recall_at_pool": owner.get("candidate_hit_at_pool"),
        "raw_top_k_same_across_request_sizes": all(
            row["raw_top_k_invariant"] for row in rows
        ),
        "raw_api_p50_ms": raw["p50_latency_ms"],
        "owner_api_p50_ms": owner["p50_latency_ms"],
        "owner_ranking_p50_ms": owner["p50_rank_latency_ms"],
        "rg_query_p50_ms": rg["p50_latency_ms"],
        "rg_index_build_ms": rg["build_latency_ms"],
        "proposed_gate": {
            "owner_hit_at_k_ge_80_percent": hit("owner_hit") >= 0.8,
            "owner_mrr_at_k_ge_60_percent": owner["ranked_mrr_at_k"] >= 0.6,
            "passed": hit("owner_hit") >= 0.8 and owner["ranked_mrr_at_k"] >= 0.6,
            "warning": "Gate is file retrieval only; does not demonstrate agent benefit.",
        },
        "rows": rows,
        "caveat": (
            "Exact-symbol navigation may be trivially solved by rg. "
            "This report alone cannot establish engineering agent speed or correctness gains."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--owner", type=Path, required=True)
    parser.add_argument("--rg", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=REPORTS / "comparison.json")
    args = parser.parse_args()
    try:
        result = compare(_read(args.raw), _read(args.owner), _read(args.rg))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(
            f"{result['suite']} | raw {result['raw_hit_at_k']:.1%}"
            f" | owner {result['owner_hit_at_k']:.1%}"
            f" | rg {result['rg_hit_at_k']:.1%}"
            f" | owner MRR {result['owner_mrr_at_k']:.3f}"
        )
        print(f"Comparison-only artifact: {args.output}")
        return 0
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(f"XERJ comparison refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
