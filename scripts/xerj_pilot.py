#!/usr/bin/env python3
"""Opt-in, local-only XERJ code-search pilot. Never used in model inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from xerj_ranking import rank_unique_files

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "nfl-pse-clean"
URL = "http://127.0.0.1:9200"
CORPUS = Path.home() / ".cache" / "nfl-pse-xerj" / "corpus"
CASES = ROOT / "configs" / "xerj" / "pilot_queries.json"
OUTPUT = ROOT / ".xerj-reports" / "pilot_report.json"
MAX_FILE_BYTES = 512_000
SOURCE_ROOTS = (
    "src/",
    "scripts/",
    "docs/",
    "tests/",
    "configs/",
    "apps/gemini-fantasy-console/src/",
    "apps/gemini-fantasy-console/server/",
    "apps/gemini-fantasy-console/shared/",
)
ROOT_FILES = {
    "README.md", "AGENTS.md", "CLAUDE.md", "CODEX.md",
    "MODEL_CARD.md", "DRAFT_DAY.md", "project_goals.md",
}
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".yaml", ".yml", ".toml", ".css", ".html"}
BLOCKED_PARTS = {
    "private", "secrets", "credentials", "node_modules", "fixtures-private",
    ".git", ".venv", "raw", "processed", "external", "live_leagues",
}
SENSITIVE = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9_]{25,}"),
    re.compile(rb"sk-[A-Za-z0-9]{24,}"),
)


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True,
    ).stdout


def eligible(path: str, mode: str = "100644") -> bool:
    p = PurePosixPath(path)
    if mode != "100644" or p.is_absolute() or ".." in p.parts:
        return False
    # Prevent evaluation leakage and the pilot's own references from ranking above code.
    if (
        path.startswith("configs/xerj/")
        or path.startswith("scripts/xerj_")
        or path.startswith("tests/test_xerj_")
        or path == "docs/tools/xerj_pilot.md"
    ):
        return False
    if any(part.startswith(".") or part.lower() in BLOCKED_PARTS for part in p.parts):
        return False
    if any(term in part.lower() for part in p.parts for term in ("secret", "credential", "token")):
        return False
    if path in ROOT_FILES:
        return True
    return any(path.startswith(root) for root in SOURCE_ROOTS) and p.suffix in SUFFIXES


def validate_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.port
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("XERJ endpoint must be plain HTTP on an explicit loopback port")
    return url.rstrip("/")


def validate_corpus(repo: Path, corpus: Path) -> Path:
    path = corpus.expanduser().absolute()
    if path.is_symlink():
        raise ValueError("Refusing symlink corpus directory")
    resolved = path.resolve()
    if resolved == repo.resolve() or repo.resolve() in resolved.parents:
        raise ValueError("XERJ corpus must stay outside the project checkout")
    return resolved


def prepare(repo: Path, corpus: Path) -> dict:
    repo = repo.resolve()
    corpus = validate_corpus(repo, corpus)
    if not (repo / "src" / "player_state_engine").is_dir():
        raise ValueError("Not an NFL Player State Engine checkout")
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    listing = git(repo, "ls-tree", "-r", "-z", "HEAD")
    selected: dict[str, bytes] = {}
    for line in listing.split(b"\0"):
        if not line:
            continue
        metadata, raw_path = line.split(b"\t", 1)
        mode, obj_type, sha = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if obj_type != "blob" or not eligible(path, mode):
            continue
        payload = git(repo, "cat-file", "blob", sha)
        if len(payload) > MAX_FILE_BYTES:
            continue
        if any(pattern.search(payload) for pattern in SENSITIVE):
            raise ValueError(f"Potential committed credential in {path}; aborting before indexing")
        selected[path] = payload

    # Only manage files from our previous manifest, never arbitrary files in this directory.
    manifest_path = corpus.parent / "snapshot_manifest.json"
    previous = {}
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("schema_version") != 1 or previous.get("corpus_dir") != str(corpus):
            raise ValueError("Unexpected existing snapshot manifest")
    known = {entry["path"] for entry in previous.get("files", [])}
    if corpus.exists():
        for item in corpus.rglob("*"):
            if item.is_symlink():
                raise ValueError(f"Refusing symlink inside staged corpus: {item}")
            if item.is_file() and item.relative_to(corpus).as_posix() not in known:
                raise ValueError(f"Refusing unrecognized corpus file: {item}")
    corpus.mkdir(parents=True, exist_ok=True)
    for stale in known - selected.keys():
        (corpus / stale).unlink(missing_ok=True)
    files = []
    for name, payload in sorted(selected.items()):
        target = corpus / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != payload:
            target.write_bytes(payload)
        files.append({
            "path": name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        })
    # Do not put this manifest in the indexed folder: it contains a source inventory.
    try:
        license_text = git(repo, "show", "HEAD:LICENSE").decode("utf-8", errors="replace")
    except subprocess.CalledProcessError:
        license_text = ""
    license_id = "MIT" if license_text.startswith("MIT License") else None
    manifest = {
        "schema_version": 1, "repo_commit": commit, "corpus_dir": str(corpus),
        "source_repository": "sidhulyalkar/nfl-player-state-engine" if repo == ROOT else None,
        "source_license": license_id,
        "files": files, "file_count": len(files), "bytes": sum(f["bytes"] for f in files),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str,
        headers: object, newurl: str,
    ) -> None:
        raise URLError("XERJ pilot refuses HTTP redirects")


def request(url: str, resource: str, body: dict | None = None, timeout: int = 20) -> dict:
    endpoint = validate_url(url)
    headers = {"Accept": "application/json"}
    key = os.getenv("XERJ_API_KEY")
    if key:
        headers["Authorization"] = f"ApiKey {key}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = Request(endpoint + resource, data=data, headers=headers,
                  method="POST" if body is not None else "GET")
    # Ignore proxy environment and refuse redirects; queries/keys stay on loopback.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(req, timeout=timeout) as response:
        return json.load(response)


def snapshot_fingerprint(manifest: dict) -> str:
    payload = {
        "repo_commit": manifest["repo_commit"],
        "files": manifest["files"],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def check_index(url: str) -> int:
    status = request(url, f"/{PREFIX}-*/_count")
    count = status.get("count")
    if not isinstance(count, int) or count <= 0:
        raise RuntimeError("Index is empty. Run index --apply after preparing the snapshot")
    return count


def source_path(hit: dict) -> str | None:
    source = hit.get("_source")
    if not isinstance(source, dict):
        return None
    path = source.get("ax_path")
    if not isinstance(path, str):
        return None
    path = path.replace("\\", "/").lstrip("./")
    return path if path else None


def benchmark(
    url: str, corpus: Path, cases_file: Path, k: int = 5,
    *, ranker: str = "raw", candidate_pool: int = 30,
) -> dict:
    if k < 1 or k > 50:
        raise ValueError("k must be between 1 and 50")
    if ranker not in {"raw", "symbol-owner"}:
        raise ValueError("Unknown ranker")
    if ranker != "raw" and not k <= candidate_pool <= 100:
        raise ValueError("candidate_pool must be between k and 100")
    fetch_size = k if ranker == "raw" else candidate_pool
    count = check_index(url)
    manifest = json.loads((corpus.parent / "snapshot_manifest.json").read_text(encoding="utf-8"))
    if manifest["corpus_dir"] != str(corpus):
        raise ValueError("Corpus/manifest mismatch")
    receipt_file = corpus.parent / "index_receipt.json"
    if not receipt_file.is_file():
        raise ValueError("No matching index receipt; run index --apply after prepare")
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    if (
        receipt.get("source_fingerprint") != snapshot_fingerprint(manifest)
        or receipt.get("url") != validate_url(url)
        or receipt.get("prefix") != PREFIX
    ):
        raise ValueError("Index receipt is stale or points at a different XERJ node")
    indexed_hashes = {f["path"]: f["sha256"] for f in manifest["files"]}
    indexed_files = set(indexed_hashes)
    cases = json.loads(cases_file.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Benchmark cases must be a nonempty JSON array")
    results = []
    for case in cases:
        if not {"id", "query", "expected_paths"} <= case.keys() or not case["expected_paths"]:
            raise ValueError("Malformed benchmark case")
        expected = set(case["expected_paths"])
        if not expected <= indexed_files:
            raise ValueError(f"Benchmark ground truth not in snapshot: {case['id']}")
        started = time.perf_counter()
        response = request(url, f"/{PREFIX}-*/_search", {
            "size": fetch_size,
            "query": {"match": {"body": case["query"]}},
            "_source": ["ax_path", "ax_locator", "title", "language", "defs"],
        })
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        hits = response.get("hits", {}).get("hits", [])
        paths = []
        evidence = []
        for hit in hits:
            path = source_path(hit)
            # Keep unrecognized hits in the ranking: removing them inflates MRR.
            paths.append(path)
            source = hit.get("_source")
            source = source if isinstance(source, dict) else {}
            evidence.append({
                "path": path,
                "in_snapshot": path in indexed_files if path is not None else False,
                "source_sha256": indexed_hashes.get(path) if path is not None else None,
                "locator": source.get("ax_locator"),
                "title": source.get("title"),
            })
        raw_top_k = paths[:k]
        first_rank = next(
            (rank for rank, path in enumerate(raw_top_k, 1) if path in expected), None
        )
        ranked_paths = None
        ranked_first_rank = None
        rank_latency_ms = 0.0
        if ranker == "symbol-owner":
            ranking_started = time.perf_counter()
            ranked_paths = rank_unique_files(paths, case["query"], corpus, indexed_hashes)[:k]
            rank_latency_ms = round((time.perf_counter() - ranking_started) * 1000, 2)
            ranked_first_rank = next(
                (rank for rank, path in enumerate(ranked_paths, 1) if path in expected),
                None,
            )
        results.append({
            "id": case["id"], "query": case["query"],
            "expected_paths": sorted(expected), "returned_paths": raw_top_k,
            "returned_evidence": evidence[:k],
            "unmapped_hits": sum(not item["in_snapshot"] for item in evidence),
            "first_rank": first_rank, "hit_at_k": first_rank is not None,
            "reciprocal_rank": round(1 / first_rank, 5) if first_rank else 0,
            "candidate_hit_at_pool": any(path in expected for path in paths),
            "raw_candidates_returned": len(paths),
            "unique_candidates_returned": len(set(paths)),
            "ranked_returned_paths": ranked_paths,
            "ranked_first_rank": ranked_first_rank,
            "ranked_hit_at_k": ranked_first_rank is not None if ranked_paths is not None else None,
            "ranked_reciprocal_rank": (
                round(1 / ranked_first_rank, 5) if ranked_first_rank else 0.0
            ) if ranked_paths is not None else None,
            "rank_latency_ms": rank_latency_ms,
            "latency_ms": elapsed_ms,
        })
    n = len(results)
    latency = sorted(row["latency_ms"] for row in results)
    return {
        "schema_version": 1, "kind": "developer_retrieval_only",
        "created_at": datetime.now(UTC).isoformat(),
        "index_prefix": PREFIX, "index_document_count": count,
        "repo_commit": manifest["repo_commit"],
        "source_fingerprint": snapshot_fingerprint(manifest),
        "suite": cases_file.name,
        "source_repository": manifest.get("source_repository"),
        "source_license": manifest.get("source_license"),
        "index_status": receipt["status"],
        "corpus_file_count": len(indexed_files),
        "k": k, "tasks": n,
        "ranker": ranker, "candidate_pool": fetch_size,
        "unmapped_result_count": sum(row["unmapped_hits"] for row in results),
        "candidate_hit_at_pool": round(
            sum(row["candidate_hit_at_pool"] for row in results) / n, 4
        ),
        "hit_at_k": round(sum(row["hit_at_k"] for row in results) / n, 4),
        "mrr_at_k": round(sum(row["reciprocal_rank"] for row in results) / n, 4),
        "ranked_hit_at_k": (
            round(sum(row["ranked_hit_at_k"] for row in results) / n, 4)
            if ranker != "raw" else None
        ),
        "ranked_mrr_at_k": (
            round(sum(row["ranked_reciprocal_rank"] for row in results) / n, 4)
            if ranker != "raw" else None
        ),
        "p50_rank_latency_ms": (
            sorted(row["rank_latency_ms"] for row in results)[(n - 1) // 2]
            if ranker != "raw" else None
        ),
        "p50_latency_ms": latency[(n - 1) // 2],
        "p95_latency_ms": latency[min(n - 1, (95 * n + 99) // 100 - 1)],
        "results": results,
        "caveat": "Retrieval correctness only; not fantasy accuracy, agent completion, token savings, or speedup.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--corpus-dir", type=Path, default=CORPUS)
    parser.add_argument("--url", default=URL)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare", help="Safely stage committed public-source-only snapshot")
    index = commands.add_parser("index", help="Index the staged snapshot (dry-run by default)")
    index.add_argument("--apply", action="store_true", help="Actually create/update the index")
    index.add_argument("--workers", type=int, default=4)
    trial = commands.add_parser("benchmark", help="Run ground-truth retrieval tasks")
    trial.add_argument("--cases", type=Path, default=CASES)
    trial.add_argument("--top-k", type=int, default=5)
    trial.add_argument("--ranker", choices=("raw", "symbol-owner"), default="raw")
    trial.add_argument("--candidate-pool", type=int, default=30)
    trial.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    try:
        corpus = validate_corpus(args.repo.resolve(), args.corpus_dir)
        url = validate_url(args.url)
        if args.command == "prepare":
            result = prepare(args.repo, corpus)
            print(f"Prepared {result['file_count']} files at {corpus}; HEAD {result['repo_commit']}")
        elif args.command == "index":
            if not (corpus.parent / "snapshot_manifest.json").exists():
                raise ValueError("Run prepare first")
            if args.workers < 1 or args.workers > 16:
                raise ValueError("workers must be 1..16")
            xerj = shutil.which("xerj")
            if not xerj:
                raise RuntimeError("XERJ binary not found. Install from official xerj-org/xerj")
            cmd = [
                xerj, "autoindex", str(corpus), "--url", url, "--prefix", PREFIX,
                "--workers", str(args.workers), "--progress", "plain",
                "--disable-feedback",
            ]
            if not args.apply:
                cmd.append("--dry-run")
            # Credentials, if needed, are inherited through XERJ_API_KEY, never arguments.
            run = subprocess.run(cmd, check=False)
            if run.returncode not in (0, 3):
                raise subprocess.CalledProcessError(run.returncode, cmd)
            if args.apply:
                documents = check_index(url)
                manifest_file = corpus.parent / "snapshot_manifest.json"
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                receipt = {
                    "schema_version": 1,
                    "prefix": PREFIX,
                    "url": url,
                    "status": "complete" if run.returncode == 0 else "partial",
                    "source_fingerprint": snapshot_fingerprint(manifest),
                    "repo_commit": manifest["repo_commit"],
                    "document_count": documents,
                    "indexed_at": datetime.now(UTC).isoformat(),
                }
                (corpus.parent / "index_receipt.json").write_text(
                    json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
                )
                print(f"Indexed {documents} documents under {PREFIX}-* ({receipt['status']})")
                if receipt["status"] == "partial":
                    print("WARNING: XERJ reported skipped/junk data; inspect autoindex status", file=sys.stderr)
            else:
                print("Dry-run only: no index was written. Use index --apply to commit.")
        elif args.command == "benchmark":
            report = benchmark(
                url, corpus, args.cases, args.top_k,
                ranker=args.ranker, candidate_pool=args.candidate_pool,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(
                f"{report['tasks']} tasks | raw hit@{report['k']} "
                f"{report['hit_at_k']:.1%} | raw MRR {report['mrr_at_k']:.3f}"
            )
            if args.ranker != "raw":
                print(
                    f"symbol-owner hit@{report['k']} {report['ranked_hit_at_k']:.1%}"
                    f" | MRR {report['ranked_mrr_at_k']:.3f}"
                    f" | candidate recall {report['candidate_hit_at_pool']:.1%}"
                )
            print(f"Report: {args.output}")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, HTTPError, URLError) as exc:
        print(f"XERJ pilot: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
