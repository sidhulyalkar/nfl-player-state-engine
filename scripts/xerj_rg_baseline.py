#!/usr/bin/env python3
"""Strong offline ripgrep + BM25-style code-navigation baseline for XERJ."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xerj_pilot import CASES, CORPUS, ROOT, snapshot_fingerprint, validate_corpus  # noqa: E402
from xerj_ranking import IDENTIFIER, owner_priority  # noqa: E402

TOKEN = re.compile(r"[a-zA-Z]+|[0-9]+")
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
STOPWORDS = frozenset({
    "a", "about", "across", "all", "an", "and", "are", "as", "at", "be", "before",
    "by", "can", "code", "component", "different", "does", "do", "for", "from",
    "get", "how", "in", "into", "is", "it", "its", "my", "of", "on", "or",
    "our", "that", "the", "them", "these", "this", "those", "to", "using",
    "we", "what", "when", "where", "which", "who", "with", "without",
})


def tokenize(value: str) -> list[str]:
    return [
        term for term in TOKEN.findall(CAMEL_BOUNDARY.sub(" ", value).lower())
        if len(term) >= 2 and term not in STOPWORDS
    ]


def read_manifest(corpus: Path) -> dict:
    manifest = json.loads(
        (corpus.parent / "snapshot_manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("schema_version") != 1 or manifest.get("corpus_dir") != str(corpus):
        raise ValueError("Missing or incompatible source snapshot manifest")
    return manifest


class LocalCatalog:
    """Load only manifest-allowlisted and SHA-verified corpus source files."""

    def __init__(self, corpus: Path, manifest: dict):
        self.corpus = corpus
        self.hashes: dict[str, str] = {}
        self.tokens: dict[str, Counter[str]] = {}
        self.lengths: dict[str, int] = {}
        df: Counter[str] = Counter()
        for entry in manifest["files"]:
            name = entry["path"]
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or any(
                part.startswith(".") for part in pure.parts
            ):
                raise ValueError(f"Unsafe manifest source path: {name}")
            file = corpus / name
            if file.is_symlink() or not file.resolve().is_relative_to(corpus):
                raise ValueError(f"Unsafe staged source path: {name}")
            payload = file.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if digest != entry["sha256"]:
                raise ValueError(f"Staged source hash mismatch: {name}")
            if name in self.hashes:
                raise ValueError(f"Duplicate path in snapshot manifest: {name}")
            self.hashes[name] = digest
            terms = Counter(tokenize(payload.decode("utf-8", errors="replace")))
            self.tokens[name] = terms
            self.lengths[name] = sum(terms.values())
            df.update(terms.keys())
        if not self.hashes:
            raise ValueError("Empty source snapshot")
        self.average_length = sum(self.lengths.values()) / len(self.hashes)
        self.document_frequency = df

    def score(self, query: str, name: str, terms: list[str]) -> float:
        doc = self.tokens[name]
        n = len(self.hashes)
        denominator = 0.25 + 0.75 * self.lengths[name] / max(self.average_length, 1)
        score = 0.0
        for token in set(terms):
            tf = doc.get(token, 0)
            if not tf:
                continue
            df = self.document_frequency[token]
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            score += idf * (tf * 2.2) / (tf + 1.2 * denominator)
        score += 1.5 * len(set(terms) & set(tokenize(name)))
        if name.startswith((
            "src/", "scripts/", "apps/gemini-fantasy-console/src/",
            "apps/gemini-fantasy-console/server/",
        )):
            score += 0.8
        if IDENTIFIER.fullmatch(query):
            score += 5.0 * owner_priority(name, query, self.corpus, self.hashes)
        return round(score, 8)


def rg_candidates(corpus: Path, query: str, timeout: int = 20) -> list[str]:
    executable = shutil.which("rg")
    if not executable:
        raise RuntimeError("ripgrep ('rg') is required for the baseline")
    terms = list(dict.fromkeys([query, *tokenize(query)]))
    terms = [term for term in terms if term and len(term) <= 256][:40]
    if not terms:
        return []
    cmd = [
        executable, "--no-ignore", "--text", "--files-with-matches", "--null",
        "--ignore-case", "--fixed-strings",
    ]
    for term in terms:
        cmd.extend(["--regexp", term])
    cmd.extend(["--", "."])
    result = subprocess.run(cmd, cwd=corpus, capture_output=True, timeout=timeout)
    if result.returncode not in {0, 1}:
        raise RuntimeError(f"ripgrep failed (exit {result.returncode})")
    return [
        part.decode("utf-8").removeprefix("./")
        for part in result.stdout.split(b"\0") if part
    ]


def search_baseline(corpus: Path, query: str, catalog: LocalCatalog, k: int) -> dict:
    start = time.perf_counter()
    paths = rg_candidates(corpus, query)
    if set(paths) - catalog.hashes.keys():
        raise ValueError("ripgrep returned a source outside the staged manifest")
    terms = tokenize(query)
    ranked = sorted(paths, key=lambda path: (-catalog.score(query, path, terms), path))
    return {
        "returned_paths": ranked[:k],
        "candidate_count": len(paths),
        "latency_ms": round((time.perf_counter() - start) * 1000, 2),
    }


def evaluate(corpus: Path, cases_file: Path, k: int = 5) -> dict:
    if not 1 <= k <= 50:
        raise ValueError("k must be 1..50")
    manifest = read_manifest(corpus)
    started = time.perf_counter()
    catalog = LocalCatalog(corpus, manifest)
    build_ms = round((time.perf_counter() - started) * 1000, 2)
    cases = json.loads(cases_file.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Benchmark cases must be a nonempty array")
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate benchmark task identifiers")
    records = []
    for case in cases:
        if not {"id", "query", "expected_paths"} <= case.keys():
            raise ValueError("Malformed benchmark case")
        expected = set(case["expected_paths"])
        if not expected or not expected <= catalog.hashes.keys():
            raise ValueError(f"Unstaged benchmark answer for {case['id']}")
        # Labels are consulted after candidate generation and ranking, never before.
        result = search_baseline(corpus, case["query"], catalog, k)
        first = next(
            (i for i, path in enumerate(result["returned_paths"], 1) if path in expected),
            None,
        )
        records.append({
            "id": case["id"], "query": case["query"],
            "expected_paths": sorted(expected), **result,
            "first_rank": first, "hit_at_k": first is not None,
            "reciprocal_rank": round(1 / first, 5) if first else 0.0,
        })
    latencies = sorted(r["latency_ms"] for r in records)
    return {
        "schema_version": 1, "kind": "developer_retrieval_baseline",
        "method": "ripgrep_bm25_path_symbol_owner",
        "created_at": datetime.now(UTC).isoformat(),
        "source_fingerprint": snapshot_fingerprint(manifest),
        "repo_commit": manifest["repo_commit"],
        "corpus_file_count": len(catalog.hashes),
        "suite": cases_file.name, "tasks": len(records), "k": k,
        "build_latency_ms": build_ms,
        "hit_at_k": round(sum(x["hit_at_k"] for x in records) / len(records), 4),
        "mrr_at_k": round(sum(x["reciprocal_rank"] for x in records) / len(records), 4),
        "p50_latency_ms": round(median(latencies), 2),
        "p95_latency_ms": latencies[min(
            len(latencies) - 1, math.ceil(0.95 * len(latencies)) - 1
        )],
        "results": records,
        "caveat": "Local source navigation only; no claim of agent or fantasy-model improvement.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--corpus-dir", type=Path, default=CORPUS)
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".xerj-reports" / "rg_baseline.json"
    )
    args = parser.parse_args()
    try:
        corpus = validate_corpus(args.repo.resolve(), args.corpus_dir)
        report = evaluate(corpus, args.cases, args.top_k)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(
            f"{report['tasks']} tasks | rg hit@{report['k']} "
            f"{report['hit_at_k']:.1%} | MRR {report['mrr_at_k']:.3f}"
            f" | report {args.output}"
        )
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"XERJ ripgrep baseline: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
