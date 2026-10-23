"""Compare independently acquired XERJ and ripgrep reports without leaking labels."""

from __future__ import annotations

import copy

import pytest

from scripts.xerj_compare import compare


def fixture_reports() -> tuple[dict, dict, dict]:
    common = {
        "repo_commit": "a" * 40,
        "source_fingerprint": "b" * 64,
        "suite": "natural_language_queries_v1.json",
        "tasks": 2,
        "k": 5,
    }
    raw_rows = [
        {"id": "a", "query": "What implements the scoring rules?",
         "expected_paths": ["src/scoring.py"],
         "returned_paths": ["docs/scoring.md"],
         "hit_at_k": False, "first_rank": None},
        {"id": "b", "query": "Where is the trade optimizer?",
         "expected_paths": ["src/trades.py"],
         "returned_paths": ["src/trades.py"],
         "hit_at_k": True, "first_rank": 1},
    ]
    owner_rows = [
        {**raw_rows[0], "ranked_hit_at_k": True, "ranked_first_rank": 2},
        {**raw_rows[1], "ranked_hit_at_k": True, "ranked_first_rank": 1},
    ]
    baseline_rows = [
        {**raw_rows[0], "hit_at_k": True, "first_rank": 2},
        {**raw_rows[1], "hit_at_k": True, "first_rank": 3},
    ]
    raw = {
        **common, "ranker": "raw", "index_status": "complete",
        "unmapped_result_count": 0, "hit_at_k": 0.5, "mrr_at_k": 0.5,
        "p50_latency_ms": 6.5, "results": raw_rows,
    }
    owner = {
        **common, "ranker": "symbol-owner", "index_status": "complete",
        "unmapped_result_count": 0, "ranked_hit_at_k": 1.0,
        "ranked_mrr_at_k": 0.75, "candidate_hit_at_pool": 1.0,
        "p50_latency_ms": 9.0, "p50_rank_latency_ms": 2.1,
        "results": owner_rows,
    }
    rg = {
        **common, "kind": "developer_retrieval_baseline",
        "hit_at_k": 1.0, "mrr_at_k": 0.4167,
        "p50_latency_ms": 4.0, "build_latency_ms": 23.0,
        "results": baseline_rows,
    }
    return raw, owner, rg


def test_comparison_reports_paired_metrics_without_claiming_agent_gain() -> None:
    raw, owner, rg = fixture_reports()
    result = compare(raw, owner, rg)
    assert result["kind"] == "retrieval_navigation_comparison_only"
    assert result["raw_hit_at_k"] == 0.5
    assert result["owner_hit_at_k"] == 1.0
    assert result["rg_hit_at_k"] == 1.0
    assert result["owner_hit_gains"] == 1
    assert result["owner_hit_regressions"] == 0
    assert result["raw_top_k_same_across_request_sizes"]
    assert result["proposed_gate"]["passed"]
    assert "agent" in result["caveat"]


@pytest.mark.parametrize("modified", ["repo_commit", "source_fingerprint", "suite", "k"])
def test_rejects_mismatched_sources(modified: str) -> None:
    raw, owner, rg = fixture_reports()
    rg[modified] = "wrong"
    with pytest.raises(ValueError, match="Incompatible"):
        compare(raw, owner, rg)


def test_rejects_incomplete_index_or_unmapped_sources() -> None:
    raw, owner, rg = fixture_reports()
    owner["unmapped_result_count"] = 1
    with pytest.raises(ValueError, match="unknown-source"):
        compare(raw, owner, rg)
    owner["unmapped_result_count"] = 0
    owner["index_status"] = "partial"
    with pytest.raises(ValueError, match="incomplete"):
        compare(raw, owner, rg)


def test_rejects_tampered_labels_or_missing_tasks() -> None:
    raw, owner, rg = fixture_reports()
    owner["results"][0]["expected_paths"] = ["tests/test_scoring.py"]
    with pytest.raises(ValueError, match="labels"):
        compare(raw, owner, rg)

    raw, owner, rg = fixture_reports()
    raw["results"] = [copy.deepcopy(raw["results"][0])] * 2
    with pytest.raises(ValueError, match="Duplicate"):
        compare(raw, owner, rg)
