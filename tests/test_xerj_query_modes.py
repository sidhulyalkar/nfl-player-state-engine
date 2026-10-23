"""Offline contract tests for optional XERJ query types, without a node."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from xerj_query_modes import QUERY_MODES, build_query  # noqa: E402


def test_lexical_maintains_frozen_first_stage_query_dsl() -> None:
    assert build_query("lexical", "player role posterior", 5) == {
        "match": {"body": "player role posterior"}
    }


def test_semantic_is_documented_body_field_query_with_bounded_k() -> None:
    assert build_query("semantic", "player role posterior", 30) == {
        "semantic": {
            "field": "body", "query": "player role posterior", "k": 30
        }
    }


def test_hybrid_rrf_unions_keyword_and_semantic_legs() -> None:
    query = build_query("hybrid", "draft qualification", 30)
    hybrid = query["hybrid"]
    assert hybrid["fusion"] == "rrf"
    assert len(hybrid["queries"]) == 2
    assert hybrid["queries"][0]["query"] == build_query(
        "lexical", "draft qualification", 30
    )
    assert hybrid["queries"][1]["query"] == build_query(
        "semantic", "draft qualification", 30
    )
    assert QUERY_MODES == ("lexical", "semantic", "hybrid")


@pytest.mark.parametrize("mode", ["unknown", "auto", "vector", ""])
def test_unsupported_modes_fail_closed(mode: str) -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        build_query(mode, "valid", 5)


@pytest.mark.parametrize("bad_size", [0, -1, 101])
def test_unbounded_requests_refused(bad_size: int) -> None:
    with pytest.raises(ValueError, match="size"):
        build_query("semantic", "valid", bad_size)


def test_empty_question_refused() -> None:
    with pytest.raises(ValueError, match="nonempty"):
        build_query("lexical", "  ", 5)
