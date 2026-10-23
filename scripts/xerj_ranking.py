"""Optional exact-symbol file-owner reranker for XERJ's retrieved candidates.

This deterministic stage is deliberately NOT a predictive model or a substitute
for source inspection. It never reads benchmark ground-truth labels.
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path, PurePosixPath

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
JS_DEF = (
    r"^\s*(?:(?:export|default|declare|async)\s+)*"
    r"(?:function|class|interface|type|const|let|var)\s+%s\b"
)


def _declaration(text: str, suffix: str, symbol: str) -> bool:
    if suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return False
        return any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == symbol
            for node in tree.body
        )
    if suffix in {".ts", ".tsx", ".js", ".jsx"}:
        return bool(re.search(JS_DEF % re.escape(symbol), text, flags=re.MULTILINE))
    return False


def owner_priority(
    path: str | None,
    query: str,
    corpus: Path,
    staged_hashes: dict[str, str],
) -> int:
    """Score an exact local *definition*, never a usage or benchmark answer key."""
    if path is None or not IDENTIFIER.fullmatch(query) or path not in staged_hashes:
        return 0
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or any(part.startswith(".") for part in pure.parts):
        raise ValueError(f"Unsafe indexed path: {path}")
    root = corpus.resolve()
    source = (corpus / path).resolve()
    if not source.is_relative_to(root) or not source.is_file() or source.is_symlink():
        raise ValueError(f"Unsafe or absent staged source: {path}")
    payload = source.read_bytes()
    if hashlib.sha256(payload).hexdigest() != staged_hashes[path]:
        raise ValueError(f"Staged source hash mismatch: {path}")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return 0
    if not _declaration(text, pure.suffix, query):
        return 0
    # Production or application source outranks test-only definitions.
    if path.startswith(("src/", "apps/gemini-fantasy-console/server/",
                        "apps/gemini-fantasy-console/src/")):
        return 2
    return 1


def rank_unique_files(
    candidate_paths: list[str | None],
    query: str,
    corpus: Path,
    staged_hashes: dict[str, str],
) -> list[str | None]:
    """First deduplicate by file; then prioritize real symbol definitions.

    This reranks *only* XERJ-returned candidates. It cannot retrieve missing
    candidates or use expected_paths from the evaluation case.
    """
    unique: list[str | None] = []
    seen: set[str | None] = set()
    for path in candidate_paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    priorities = {
        path: owner_priority(path, query, corpus, staged_hashes)
        for path in unique
    }
    # Stable tie-break: XERJ's original order.
    return sorted(unique, key=lambda path: -priorities[path])
