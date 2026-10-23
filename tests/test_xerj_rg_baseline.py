"""Offline tests for strong source-navigation baseline and clean benchmark isolation."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import xerj_rg_baseline as baseline
from scripts import xerj_pilot as pilot


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    (root / "src/player_state_engine/fantasy").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "docs").mkdir()
    (root / "configs/xerj").mkdir(parents=True)
    (root / "src/player_state_engine/fantasy/scoring.py").write_text(
        "def score_quantile_components(stats):\n    return stats\n",
        encoding="utf-8",
    )
    (root / "tests/test_scoring.py").write_text(
        "from player_state_engine.fantasy.scoring import score_quantile_components\n",
        encoding="utf-8",
    )
    (root / "docs/guide.md").write_text("Roster position scoring and league rules.\n")
    (root / "configs/xerj/pilot_queries.json").write_text(
        '{"query": "score_quantile_components", '
        '"expected_paths": ["src/player_state_engine/fantasy/scoring.py"]}\n'
    )
    _git(root, "init")
    _git(root, "config", "user.email", "tester@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "test")
    staged = tmp_path / "staged" / "corpus"
    pilot.prepare(root, staged)
    return root, staged


def test_answer_keys_not_staged(corpus: tuple[Path, Path]) -> None:
    _, staged = corpus
    assert not (staged / "configs/xerj/pilot_queries.json").exists()
    manifest = baseline.read_manifest(staged)
    assert "configs/xerj/pilot_queries.json" not in {
        f["path"] for f in manifest["files"]
    }


def test_tokenizer_splits_symbol_names_and_discards_stopwords() -> None:
    assert baseline.tokenize("Where is score_quantile_components used?") == [
        "score", "quantile", "components", "used"
    ]
    assert "where" not in baseline.tokenize("Where are forecast statistics evaluated?")


def test_scoring_prioritizes_owner_over_import_reference(
    corpus: tuple[Path, Path]
) -> None:
    _, staged = corpus
    catalog = baseline.LocalCatalog(staged, baseline.read_manifest(staged))
    owner = "src/player_state_engine/fantasy/scoring.py"
    test = "tests/test_scoring.py"
    assert catalog.score("score_quantile_components", owner, baseline.tokenize(
        "score_quantile_components"
    )) > catalog.score("score_quantile_components", test, baseline.tokenize(
        "score_quantile_components"
    ))


def test_evaluate_keeps_ground_truth_out_of_retrieval(
    corpus: tuple[Path, Path], tmp_path: Path
) -> None:
    _, staged = corpus
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps([{
        "id": "query1",
        "query": "score_quantile_components",
        "expected_paths": ["src/player_state_engine/fantasy/scoring.py"],
    }]))
    paths = [
        "tests/test_scoring.py", "src/player_state_engine/fantasy/scoring.py"
    ]
    with patch.object(baseline, "rg_candidates", return_value=paths) as find:
        result = baseline.evaluate(staged, cases_file, k=2)
    find.assert_called_once()
    assert find.call_args.args[1] == "score_quantile_components"
    assert result["kind"] == "developer_retrieval_baseline"
    assert len(result["repo_commit"]) == 40
    assert result["hit_at_k"] == 1.0
    assert result["mrr_at_k"] == 1.0
    assert result["results"][0]["first_rank"] == 1


def test_tampered_source_fails_closed(corpus: tuple[Path, Path]) -> None:
    _, staged = corpus
    (staged / "docs/guide.md").write_text("tampered\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        baseline.LocalCatalog(staged, baseline.read_manifest(staged))


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep unavailable")
def test_real_ripgrep_only_searches_staged_files(corpus: tuple[Path, Path]) -> None:
    _, staged = corpus
    actual = baseline.rg_candidates(staged, "score_quantile_components")
    assert "src/player_state_engine/fantasy/scoring.py" in actual
    assert "tests/test_scoring.py" in actual
    assert not any(name.startswith("configs/xerj/") for name in actual)


def test_out_of_manifest_rg_result_is_rejected(corpus: tuple[Path, Path]) -> None:
    _, staged = corpus
    catalog = baseline.LocalCatalog(staged, baseline.read_manifest(staged))
    with patch.object(baseline, "rg_candidates", return_value=["private.key"]):
        with pytest.raises(ValueError, match="outside"):
            baseline.search_baseline(staged, "scoring", catalog, 5)


def test_missing_ripgrep_is_reported(corpus: tuple[Path, Path]) -> None:
    _, staged = corpus
    with patch.object(baseline.shutil, "which", return_value=None):
        with pytest.raises(RuntimeError, match="ripgrep"):
            baseline.rg_candidates(staged, "scoring")


def test_natural_language_cases_are_preregistered_and_without_symbol_spelling() -> None:
    root = Path(__file__).resolve().parents[1]
    file = root / "configs/xerj/natural_language_queries_v1.json"
    cases = json.loads(file.read_text(encoding="utf-8"))
    assert len(cases) == 20
    assert len({c["id"] for c in cases}) == len(cases)
    assert all(c["query"].endswith("?") for c in cases)
    assert all(len(c["expected_paths"]) == 1 for c in cases)
    assert all((root / c["expected_paths"][0]).is_file() for c in cases)
    # Every query must be phrased as an engineering problem, not an identifier.
    assert all(not re.search(r"\b(?:def|class) [A-Za-z_]", c["query"]) for c in cases)
