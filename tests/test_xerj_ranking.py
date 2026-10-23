"""Unit tests for local XERJ file-owner ranking semantics."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.xerj_ranking import owner_priority, rank_unique_files


def _stage(root: Path, relative: str, content: str) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode()).hexdigest()


def test_owner_beats_imports_tests_and_reexports(tmp_path: Path) -> None:
    scores = {
        "src/player_state_engine/fantasy/engine.py": _stage(
            tmp_path, "src/player_state_engine/fantasy/engine.py",
            "def actual_owner():\n    return None\n",
        ),
        "src/player_state_engine/fantasy/__init__.py": _stage(
            tmp_path, "src/player_state_engine/fantasy/__init__.py",
            "from .engine import actual_owner\n",
        ),
        "tests/test_engine.py": _stage(
            tmp_path, "tests/test_engine.py",
            "def test_actual_owner():\n    assert True\n",
        ),
    }
    paths = [
        "tests/test_engine.py",
        "src/player_state_engine/fantasy/__init__.py",
        "tests/test_engine.py",
        "src/player_state_engine/fantasy/engine.py",
    ]
    ranked = rank_unique_files(paths, "actual_owner", tmp_path, scores)
    assert ranked == [
        "src/player_state_engine/fantasy/engine.py",
        "tests/test_engine.py",
        "src/player_state_engine/fantasy/__init__.py",
    ]
    assert owner_priority("tests/test_engine.py", "actual_owner", tmp_path, scores) == 0


@pytest.mark.parametrize("symbol", ["SleeperImporter", "ESPNImporter"])
def test_python_owner_recognition(tmp_path: Path, symbol: str) -> None:
    path = "src/player_state_engine/integrations/importer.py"
    hashes = {path: _stage(tmp_path, path, f"class {symbol}:\n    pass\n")}
    assert owner_priority(path, symbol, tmp_path, hashes) == 2


def test_typescript_owner_and_usage(tmp_path: Path) -> None:
    real = "apps/gemini-fantasy-console/server/gemini.ts"
    usage = "apps/gemini-fantasy-console/server/tools.ts"
    hashes = {
        real: _stage(tmp_path, real, "export function selectFallbackTool() { return null; }"),
        usage: _stage(tmp_path, usage, "selectFallbackTool();"),
    }
    assert rank_unique_files([usage, real], "selectFallbackTool", tmp_path, hashes) == [
        real, usage,
    ]


def test_natural_language_queries_preserve_engine_order(tmp_path: Path) -> None:
    path = "src/player_state_engine/fantasy/scoring.py"
    hashes = {path: _stage(tmp_path, path, "def score_fantasy_stats(): pass\n")}
    assert rank_unique_files(
        [None, path], "How is a player's league score computed?", tmp_path, hashes,
    ) == [None, path]


def test_missing_symbol_is_not_invented(tmp_path: Path) -> None:
    path = "src/player_state_engine/models/hybrid.py"
    hashes = {path: _stage(tmp_path, path, "def other_symbol(): pass\n")}
    assert owner_priority(path, "not_in_file", tmp_path, hashes) == 0


def test_source_path_traversal_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsafe"):
        owner_priority("../secret.py", "secret", tmp_path, {"../secret.py": "0" * 64})


def test_changed_source_is_detected(tmp_path: Path) -> None:
    path = "src/player_state_engine/models/hybrid.py"
    hashes = {path: _stage(tmp_path, path, "class HybridQuantileModelBundle: pass\n")}
    (tmp_path / path).write_text("class HybridQuantileModelBundle: pass\n# mutated\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        rank_unique_files([path], "HybridQuantileModelBundle", tmp_path, hashes)
