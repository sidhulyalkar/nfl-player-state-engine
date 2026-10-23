"""Read-only XERJ query variants for controlled retrieval diagnosis.

No benchmark labels, filesystem paths or model-serving inputs influence these queries.
"""

from __future__ import annotations

QUERY_MODES = ("lexical", "semantic", "hybrid")


def build_query(mode: str, question: str, size: int) -> dict:
    """Return the documented XERJ search query DSL for a single question."""
    if mode not in QUERY_MODES:
        raise ValueError(f"Unsupported XERJ query mode: {mode}")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Search question must be nonempty")
    if not 1 <= size <= 100:
        raise ValueError("Search size must be 1..100")

    keyword = {"match": {"body": question}}
    if mode == "lexical":
        return keyword

    # Requires an index where 'body' is mapped as semantic_text.
    semantic = {"semantic": {"field": "body", "query": question, "k": size}}
    if mode == "semantic":
        return semantic

    # Independent BM25 and semantic legs with rank-based fusion; this is
    # exploratory, and not a substitute for a strong local rg comparator.
    return {
        "hybrid": {
            "queries": [
                {"query": keyword},
                {"query": semantic},
            ],
            "fusion": "rrf",
        }
    }
