"""Offline contract tests for the opt-in XERJ developer-search pilot."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "xerj_pilot.py"
# The standalone script imports a sibling module when executed from scripts/.
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("pse_xerj_pilot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def local_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "checkout"
    (repo / "src/player_state_engine/fantasy").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "data/product/live_leagues").mkdir(parents=True)
    (repo / "src/player_state_engine/fantasy/scoring.py").write_text(
        "def score_quantile_components():\n    return 1\n", encoding="utf-8"
    )
    (repo / "docs/guide.md").write_text("research-only context\n", encoding="utf-8")
    (repo / "data/product/live_leagues/actual.json").write_text(
        '{"access_token":"private"}', encoding="utf-8"
    )
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "XERJ Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo


def test_snapshot_uses_committed_allowlisted_content(local_repo: Path, tmp_path: Path) -> None:
    scoring = local_repo / "src/player_state_engine/fantasy/scoring.py"
    scoring.write_text("uncommitted secret content\n", encoding="utf-8")
    (local_repo / "src/player_state_engine/fantasy/untracked.py").write_text(
        "untracked data\n", encoding="utf-8"
    )
    corpus = tmp_path / "index-corpus"
    manifest = pilot.prepare(local_repo, corpus)
    names = [f["path"] for f in manifest["files"]]
    assert names == ["docs/guide.md", "src/player_state_engine/fantasy/scoring.py"]
    assert manifest["repo_commit"] == pilot.git(local_repo, "rev-parse", "HEAD").decode().strip()
    assert (corpus / "src/player_state_engine/fantasy/scoring.py").read_text() == (
        "def score_quantile_components():\n    return 1\n"
    )
    assert not (corpus / "data").exists()
    assert "untracked" not in str(names)
    assert manifest["files"][1]["sha256"] == hashlib.sha256(
        (corpus / names[1]).read_bytes()
    ).hexdigest()
    assert not (corpus / "snapshot_manifest.json").exists()


def test_snapshot_idempotent_and_prunes_deleted_tracked_file(
    local_repo: Path, tmp_path: Path
) -> None:
    corpus = tmp_path / "corpus"
    before = pilot.prepare(local_repo, corpus)
    assert pilot.prepare(local_repo, corpus) == before
    _git(local_repo, "rm", "docs/guide.md")
    _git(local_repo, "commit", "-m", "remove doc")
    after = pilot.prepare(local_repo, corpus)
    assert after["file_count"] == before["file_count"] - 1
    assert not (corpus / "docs/guide.md").exists()


def test_snapshot_rejects_unknown_staged_files(local_repo: Path, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    pilot.prepare(local_repo, corpus)
    (corpus / "extra.env").write_text("UNINDEXED=private\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unrecognized"):
        pilot.prepare(local_repo, corpus)


def test_snapshot_rejects_potential_committed_credentials(
    local_repo: Path, tmp_path: Path
) -> None:
    source = local_repo / "src/player_state_engine/fantasy/scoring.py"
    source.write_text(
        "credential = '" + "-----BEGIN " + "RSA PRIVATE KEY-----" + "'\n",
        encoding="utf-8",
    )
    _git(local_repo, "add", ".")
    _git(local_repo, "commit", "-m", "fixture credential")
    with pytest.raises(ValueError, match="Potential committed credential"):
        pilot.prepare(local_repo, tmp_path / "corpus")


def test_snapshot_rejects_checkout_destination(local_repo: Path) -> None:
    with pytest.raises(ValueError, match="outside"):
        pilot.prepare(local_repo, local_repo / "local-index")


def test_excludes_symlinks_hidden_and_untrusted_paths() -> None:
    assert pilot.eligible("src/player_state_engine/models/hybrid.py")
    assert pilot.eligible("apps/gemini-fantasy-console/server/gemini.ts")
    assert not pilot.eligible("src/player_state_engine/models/model.py", "120000")
    assert not pilot.eligible("src/player_state_engine/.env")
    assert not pilot.eligible("src/player_state_engine/credentials/token.py")
    assert not pilot.eligible("data/product/live_leagues/123.json")
    assert not pilot.eligible("artifacts/models/registry.json")
    assert not pilot.eligible("apps/gemini-fantasy-console/package-lock.json")
    assert not pilot.eligible("configs/xerj/pilot_queries.json")
    assert not pilot.eligible("configs/xerj/natural_language_queries_v1.json")
    assert not pilot.eligible("tests/test_xerj_pilot.py")
    assert not pilot.eligible("tests/test_xerj_ranking.py")
    assert not pilot.eligible("scripts/xerj_rg_baseline.py")
    assert not pilot.eligible("docs/tools/xerj_pilot.md")
    assert not pilot.eligible("../outside.py")


@pytest.mark.parametrize("bad_url", [
    "https://127.0.0.1:9200",
    "http://10.0.0.1:9200",
    "http://example.com:9200",
    "http://127.0.0.1:9200/other",
    "http://user:password@localhost:9200",
    "http://localhost",
    "file:///tmp/data",
])
def test_remote_or_ambiguous_endpoint_fails_closed(bad_url: str) -> None:
    with pytest.raises(ValueError):
        pilot.validate_url(bad_url)


def test_redirect_is_refused_without_following_external_links() -> None:
    with pytest.raises(pilot.URLError, match="redirects"):
        pilot._NoRedirect().redirect_request(
            None, None, 302, "Found", {}, "https://external.invalid/leak"
        )


def _index_receipt(corpus: Path) -> None:
    manifest = json.loads((corpus.parent / "snapshot_manifest.json").read_text())
    receipt = {
        "schema_version": 1, "source_fingerprint": pilot.snapshot_fingerprint(manifest),
        "url": pilot.URL, "prefix": pilot.PREFIX, "status": "complete",
    }
    (corpus.parent / "index_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")


def test_ground_truth_benchmark_and_missing_hits(local_repo: Path, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    pilot.prepare(local_repo, corpus)
    _index_receipt(corpus)
    cases = [
        {"id": "a", "query": "score_quantile_components",
         "expected_paths": ["src/player_state_engine/fantasy/scoring.py"]},
        {"id": "b", "query": "not present", "expected_paths": ["docs/guide.md"]},
    ]
    case_file = tmp_path / "cases.json"
    case_file.write_text(json.dumps(cases), encoding="utf-8")

    def fake_request(url: str, resource: str, body: dict | None = None) -> dict:
        if resource.endswith("/_count"):
            return {"count": 7}
        assert resource == "/nfl-pse-*/_search"
        if body["query"]["match"]["body"] == "score_quantile_components":
            paths = ["docs/stale-file.md", "src/player_state_engine/fantasy/scoring.py"]
        else:
            paths = ["docs/not-the-answer.md"]
        return {"hits": {"hits": [{"_source": {"ax_path": path}} for path in paths]}}

    with patch.object(pilot, "request", side_effect=fake_request):
        result = pilot.benchmark(pilot.URL, corpus, case_file, k=5)
    assert result["index_document_count"] == 7
    assert result["tasks"] == 2
    assert result["hit_at_k"] == 0.5
    assert result["mrr_at_k"] == 0.25
    assert result["unmapped_result_count"] == 2
    assert result["kind"] == "developer_retrieval_only"
    assert result["index_status"] == "complete"
    assert result["results"][0]["returned_evidence"][1]["source_sha256"]
    assert result["results"][0]["returned_evidence"][0]["in_snapshot"] is False
    assert result["results"][0]["first_rank"] == 2
    assert result["results"][1]["first_rank"] is None
    assert result["results"][1]["returned_paths"] == ["docs/not-the-answer.md"]


def test_symbol_owner_ranker_keeps_unmodified_raw_comparison(
    local_repo: Path, tmp_path: Path
) -> None:
    corpus = tmp_path / "corpus"
    pilot.prepare(local_repo, corpus)
    _index_receipt(corpus)
    cases = [{
        "id": "owner", "query": "score_quantile_components",
        "expected_paths": ["src/player_state_engine/fantasy/scoring.py"],
    }]
    case_file = tmp_path / "cases.json"
    case_file.write_text(json.dumps(cases), encoding="utf-8")

    def fake_request(url: str, resource: str, body: dict | None = None) -> dict:
        if resource.endswith("/_count"):
            return {"count": 2}
        assert body["size"] == 3
        return {"hits": {"hits": [
            {"_source": {"ax_path": "docs/guide.md"}},
            {"_source": {"ax_path": "docs/guide.md", "ax_locator": "s1"}},
            {"_source": {"ax_path": "src/player_state_engine/fantasy/scoring.py"}},
        ]}}

    with patch.object(pilot, "request", side_effect=fake_request):
        report = pilot.benchmark(
            pilot.URL, corpus, case_file, k=1, ranker="symbol-owner", candidate_pool=3,
        )

    assert report["hit_at_k"] == 0.0
    assert report["mrr_at_k"] == 0.0
    assert report["candidate_hit_at_pool"] == 1.0
    assert report["ranked_hit_at_k"] == 1.0
    assert report["ranked_mrr_at_k"] == 1.0
    assert report["results"][0]["ranked_first_rank"] == 1
    assert report["results"][0]["unique_candidates_returned"] == 2
    assert report["results"][0]["returned_paths"] == ["docs/guide.md"]


def test_symbol_owner_refuses_modified_staged_source(
    local_repo: Path, tmp_path: Path
) -> None:
    corpus = tmp_path / "corpus"
    pilot.prepare(local_repo, corpus)
    scoring = corpus / "src/player_state_engine/fantasy/scoring.py"
    scoring.write_text("def score_quantile_components(): pass\n# tampered\n")

    from xerj_ranking import owner_priority

    manifest = json.loads((corpus.parent / "snapshot_manifest.json").read_text())
    hashes = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    with pytest.raises(ValueError, match="hash mismatch"):
        owner_priority(
            "src/player_state_engine/fantasy/scoring.py",
            "score_quantile_components", corpus, hashes,
        )


def test_benchmark_rejects_ground_truth_outside_snapshot(
    local_repo: Path, tmp_path: Path
) -> None:
    corpus = tmp_path / "corpus"
    pilot.prepare(local_repo, corpus)
    _index_receipt(corpus)
    cases = [{"id": "x", "query": "anything", "expected_paths": ["private.key"]}]
    case_file = tmp_path / "cases.json"
    case_file.write_text(json.dumps(cases), encoding="utf-8")
    with patch.object(pilot, "request", return_value={"count": 1}):
        with pytest.raises(ValueError, match="ground truth"):
            pilot.benchmark(pilot.URL, corpus, case_file)


def test_benchmark_rejects_stale_index(local_repo: Path, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    pilot.prepare(local_repo, corpus)
    _index_receipt(corpus)
    receipt_path = corpus.parent / "index_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["source_fingerprint"] = "wrong-commit"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    cases = [{"id": "a", "query": "anything", "expected_paths": ["docs/guide.md"]}]
    case_file = tmp_path / "cases.json"
    case_file.write_text(json.dumps(cases), encoding="utf-8")
    with patch.object(pilot, "request", return_value={"count": 3}):
        with pytest.raises(ValueError, match="stale"):
            pilot.benchmark(pilot.URL, corpus, case_file)


def test_nonempty_index_is_mandatory() -> None:
    with patch.object(pilot, "request", return_value={"count": 0}):
        with pytest.raises(RuntimeError, match="empty"):
            pilot.check_index(pilot.URL)


def test_index_dry_run_is_default(local_repo: Path, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    pilot.prepare(local_repo, corpus)
    with (
        patch.object(pilot.shutil, "which", return_value="/usr/local/bin/xerj"),
        patch.object(pilot.subprocess, "run") as run,
    ):
        run.return_value.returncode = 0
        status = pilot.main([
            "--repo", str(local_repo), "--corpus-dir", str(corpus),
            "index",
        ])
    assert status == 0
    command = run.call_args.args[0]
    assert command[:2] == ["/usr/local/bin/xerj", "autoindex"]
    assert "--dry-run" in command and "--prefix" in command
    assert "nfl-pse" in command


def test_benchmark_cases_unique_and_tracked_in_repo() -> None:
    cases = json.loads(pilot.CASES.read_text(encoding="utf-8"))
    assert len(cases) >= 15
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        assert case["query"]
        for target in case["expected_paths"]:
            assert pilot.eligible(target)
            assert (pilot.ROOT / target).is_file()
