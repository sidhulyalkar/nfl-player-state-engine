# XERJ local pilot for NFL Player State Engine

**Status:** optional developer search experiment, not a fantasy model input or production dependency. XERJ is a local-first code/document search engine with a separate MCP server. Our goal is to see whether source retrieval helps agents find the real implementation and its boundaries.

## Hypothesis and scope

Index NFL Player State Engine source and documentation first, then compare retrieval against normal repository navigation on twenty preregistered engineering tasks. If useful, repeat using distinct namespaces for neurOS and MindForge, without mixing corpus content or allowing reference code to override project tests.

## Security contract

The script at scripts/xerj_pilot.py prepares a **committed-HEAD-only** mirror in ~/.cache/nfl-pse-xerj/corpus. It never copies untracked or modified working-tree content. Only explicitly selected src/, scripts/, docs/, tests/, configs/, and frontend code plus root guides are eligible; all XERJ benchmark fixtures and pilot tooling are separately excluded. It excludes data/, artifacts/, private league snapshots, credentials, hidden files, binaries, lockfiles, symlinks, and oversized files. Several known credential patterns abort staging.

These rules are **defense in depth**, not a guarantee that no secret has ever been committed. Review snapshot_manifest.json before indexing. This manifest, kept in the parent of the corpus, records HEAD, source paths, SHA-256 hashes and byte sizes. All generated local reports are gitignored.

XERJ's node storage must stay outside both corpus and checkout (for example ~/.local/share/nfl-pse-xerj/node); otherwise a search engine can index its own storage. The first exploratory run used the nfl-pse prefix, which may retain benchmark answer-key documents. All subsequent clean qualification runs MUST use the dedicated nfl-pse-clean prefix, never the default ax or old contaminated namespace. Never delete unrelated indexes to resolve a prefix collision.

An XERJ node launched with --insecure has no TLS or API authentication; only use it bound to 127.0.0.1 on a trusted computer. The pilot wrapper rejects nonloopback endpoints. An authenticated local node is also supported using XERJ_API_KEY in the environment, never in repository files or command arguments.

**Invariant:** XERJ helps find code. It may not directly modify projection, model promotion, source-cutoff checks, league scoring, production readiness, or any fantasy decision. The Python API remains authoritative, and negative controls/frozen evaluations remain mandatory.

## Setup

Install and verify the XERJ executable from the official project: https://github.com/xerj-org/xerj . The verified CLI reference is https://www.xerj.org/docs/cli .

On macOS/Linux (for Windows PowerShell use equivalent paths and a terminal for the XERJ server):

Terminal A:

    mkdir -p "$HOME/.local/share/nfl-pse-xerj/node"
    xerj --insecure --disable-feedback --data-dir "$HOME/.local/share/nfl-pse-xerj/node"

Terminal B, from a clean NFL Player State Engine checkout:

    python scripts/xerj_pilot.py prepare
    python scripts/xerj_pilot.py index
    # Inspect the dry-run plan and ~/.cache/nfl-pse-xerj/snapshot_manifest.json
    python scripts/xerj_pilot.py index --apply
    xerj autoindex map --url http://127.0.0.1:9200
    xerj search --url http://127.0.0.1:9200 --prefix nfl-pse-clean -k 5 "assess_draft_release_readiness"
    python scripts/xerj_pilot.py benchmark

The first index command is a **dry-run by default**. Only --apply writes the index. A successful apply writes a local index_receipt.json alongside snapshot_manifest.json, recording the source fingerprint, prefix, local node URL, and complete/partial indexing status. A benchmark refuses an absent or stale receipt. When XERJ reports skipped/junk files, the receipt records partial, and coverage must be inspected before claiming completeness. The benchmark report appears under .xerj-reports/pilot_report.json and is not committed. Each source snapshot is keyed to one Git HEAD; repeat prepare and index when you commit new changes. Dirty changes are intentionally invisible.

If using an authenticated node, omit --insecure and export XERJ_API_KEY from its locally generated admin key. The autoindex client does not load that key from the server TOML automatically.

## Agent host / MCP integration

After starting the node, the official CLI provides:

    xerj init

Or point your local host's stdio MCP configuration to command xerj and args ["mcp", "--url", "http://127.0.0.1:9200"]. Store configuration outside the repository. The MCP command does not start a node on its own.

Agents should use prefix nfl-pse-clean and return the exact ax_path, XERJ locator or line (when actually present), and the manifest's Git SHA. Open the real source and related tests before editing. If an indexed file differs from HEAD, re-run staging and indexing.

## What the benchmark measures

configs/xerj/pilot_queries.json contains twenty fixed tasks with query text and ground-truth source paths. The wrapper sends lexical match queries to the XERJ body field, scoped to nfl-pse-clean-*, and records:

| Metric | Meaning |
| --- | --- |
| hit@5 | Fraction of tasks retrieving at least one expected file in top five |
| MRR@5 | Average reciprocal rank of first expected file |
| Request latency | Elapsed HTTP time per task, including network overhead on localhost |
| Provenance | Returned ax_path; staged source paths and hashes recorded by commit |

This **does not** measure code correctness, task completion, token savings, fantasy performance, or retrieval line-level accuracy. If XERJ infers different fields, inspect autoindex map and the live mapping; do not silently mark missing information as discovered.

For the second-stage paired agent benchmark, hide ground-truth labels, randomize task order, and compare separate fresh runs using repository navigation versus XERJ. Record exact source-and-line correctness, regression tests, time-to-evidence, host-reported tokens/runtime, fabricated citations, and breaches of modeling cutoffs, league scoring, or production authority. Keep all failed trials in the results.

## Proposed acceptance gates (not yet observed)

The initial local pilot is ready for judgment once: the safe snapshot is inspected, all twenty expected paths are present in HEAD, an index has a nonzero document count, a machine-readable JSON report is saved, the Python tests/CI pass, and no credentials leave the machine.

Suggested decision thresholds are hit@5 >= 0.80, MRR@5 >= 0.60, and no loss of task correctness in the blinded baseline-vs-XERJ study. These are goals, **not reported performance**. Treat partial autoindex status, missing file families, or mismatched mapping as blockers to a coverage claim, not as success.

## Troubleshooting

- 401 Unauthorized: the node expects XERJ_API_KEY; do not commit it or embed it into MCP JSON.
- Empty index: confirm the node is running, use autoindex map, and rerun prepare, dry-run and --apply. The wrapper does not create or wipe a node automatically.
- A prefix is already occupied: investigate existing indexes instead of deleting anything you did not create.
- Source retrieval misses: inspect the real field mapping and returned ax_path; a nonexistent expected file or unknown schema is an evaluation failure.
- Index completes with warnings/partial status: inspect autoindex status and coverage before interpreting benchmark results.
- Repo functions as normal without XERJ: all developer tooling is opt-in, with offline unit tests only in CI.

## First local results and second-stage diagnostic run (October 23, 2026)

The real local run at commit `6782c0759329466fa0a10ff23f9e3b86932996f3` indexed **600 files / 4,562 documents** with `index_status=complete` and `unmapped_result_count=0`. Across 20 exact-symbol queries, raw **Hit@5 was 0.85** and **MRR@5 was 0.4017**, with **p50 6.5 ms / p95 13.84 ms** API latency. It meets the proposed 0.80 Hit@5 target but misses the 0.60 MRR target. The three misses were `03-candidate-actionability`, `13-sleeper-ingestion`, and `14-espn-ingestion`. No agent task-speed or correctness improvement was measured.

Observed competing matches include tests, re-exports, routes, and the XERJ pilot's own documentation. Multiple XERJ document chunks can share one `ax_path`, causing the same file to occupy multiple top-k positions. `source_sha256` is a hash of a staged *whole file*, not proof the returned passage is a definition.

The second-stage mode runs **two separate metrics on the same query response**: the original raw chunk-level top five, and a deterministic deduplicated, exact-symbol-owner-aware ranking over a larger raw candidate pool. This stage uses Python AST definitions and conservative TypeScript/JavaScript declarations. It never reads `expected_paths`, and cannot recover a correct file absent from XERJ's candidate pool. It records candidate recall, raw/ranked Hit@5, raw/ranked MRR@5, unmapped hits, API and local ranking latency. It makes no assertion that results have improved until a new real run completes.

After checking out the latest branch commit, **rebuild the index** because the staged-source fingerprint changes:

    python scripts/xerj_pilot.py prepare
    python scripts/xerj_pilot.py index
    python scripts/xerj_pilot.py index --apply
    python scripts/xerj_pilot.py benchmark --output .xerj-reports/pilot_raw_v2.json
    python scripts/xerj_pilot.py benchmark --ranker symbol-owner --candidate-pool 30 \
        --output .xerj-reports/pilot_symbol_owner_v2.json

The original 2026-10-23 run is the frozen historical baseline; don't replace or relabel it as a v2 run. Ranker results are not necessarily better than raw baseline and require independent measurement.

**Crucial caveat:** Exact function and class symbol lookups are often trivial for local `rg` or AST-based navigation. Symbol-owner reranking is a diagnostic for navigation quality, *not evidence that XERJ beats ordinary code search*. Next, preregister natural-language tasks that don't provide exact symbol names and run a randomized, blinded, paired agent study against a strong `rg`+repo-tool baseline before deciding to roll out to other repositories.

## Clean natural-language comparison protocol (v1)

The first October 23 pilot was **exploratory, not fully blinded**: the original corpus allowlist included configs/xerj/ and could therefore index the query labels and expected source paths. Some benchmark-specific tests and self-referential documentation were also eligible. This is a reproducibility risk even if a particular result did not use those documents. Preserve its 85% Hit@5 / 0.4017 MRR@5 as an exploratory observation, not a qualified search-result claim.

The corrected allowlist excludes configs/xerj/, scripts/xerj_*, tests/test_xerj_*, and docs/tools/xerj_pilot.md. The clean index uses **nfl-pse-clean** rather than nfl-pse, so previous answer-key chunks cannot persist in a reused namespace. New CI checks both suites' answers are present in the safely staged code, while the evaluation fixtures themselves are absent from the index.

Twenty frozen problem-oriented, natural-language questions live in configs/xerj/natural_language_queries_v1.json. These do not disclose the exact function names to the retrieval algorithm, although the source owners and labels were authored with knowledge of the repository. This suite is a developer-retrieval experiment, not a truly independent blind external user benchmark.

After checking out the most recent PR branch and starting the XERJ server, **inspect the staging manifest and dry-run plan before indexing**:

    python scripts/xerj_pilot.py prepare
    python scripts/xerj_pilot.py index
    python scripts/xerj_pilot.py index --apply

Then run the exact-symbol suite using the clean index:

    python scripts/xerj_pilot.py benchmark \
      --cases configs/xerj/pilot_queries.json \
      --output .xerj-reports/clean_exact_raw.json

    python scripts/xerj_pilot.py benchmark \
      --cases configs/xerj/pilot_queries.json \
      --ranker symbol-owner --candidate-pool 30 \
      --output .xerj-reports/clean_exact_owner.json

    python scripts/xerj_rg_baseline.py \
      --cases configs/xerj/pilot_queries.json \
      --output .xerj-reports/clean_exact_rg.json

    python scripts/xerj_compare.py \
      --raw .xerj-reports/clean_exact_raw.json \
      --owner .xerj-reports/clean_exact_owner.json \
      --rg .xerj-reports/clean_exact_rg.json \
      --output .xerj-reports/clean_exact_compare.json

Repeat on the **natural-language suite**, without modifying its frozen labels:

    python scripts/xerj_pilot.py benchmark \
      --cases configs/xerj/natural_language_queries_v1.json \
      --output .xerj-reports/clean_natural_raw.json

    python scripts/xerj_pilot.py benchmark \
      --cases configs/xerj/natural_language_queries_v1.json \
      --ranker symbol-owner --candidate-pool 30 \
      --output .xerj-reports/clean_natural_owner.json

    python scripts/xerj_rg_baseline.py \
      --cases configs/xerj/natural_language_queries_v1.json \
      --output .xerj-reports/clean_natural_rg.json

    python scripts/xerj_compare.py \
      --raw .xerj-reports/clean_natural_raw.json \
      --owner .xerj-reports/clean_natural_owner.json \
      --rg .xerj-reports/clean_natural_rg.json \
      --output .xerj-reports/clean_natural_compare.json

The local baseline requires ripgrep installed and available as rg. It uses the **same checked, immutable staged source snapshot** as XERJ, lexical ripgrep candidate discovery, BM25-style term-frequency weighting, path tokens, and exact-definition verification for symbol-name queries. It has no network dependency, does not access expected paths during ranking, and separately records the local catalog's build cost. Its query latencies cannot be compared naively against only XERJ HTTP request times because XERJ indexing has already been amortized. Record the XERJ indexing cost and node startup alongside the reports when evaluating end-to-end workflows.

The comparison report refuses missing source fingerprints, mismatched Git commits, inconsistent query labels, incomplete indexes, or unknown XERJ sources. It keeps raw results, deduplicated reranking, and rg measurements distinct. Querying XERJ with a larger pool can change the raw order, so the report also records whether top-k raw results match between request sizes. Treat such differences as a search-engine stability diagnostic.

**Honest go/no-go:**
- The exact-symbol suite is a sanity check, not a competitive demonstration against rg.
- The natural-language suite must meet the proposed retrieval thresholds and preferably compete with the strong local baseline before an agent study.
- Only randomized, isolated end-to-end developer tasks with hidden labels can establish agent correctness, latency, or token improvements. Do not claim benefits to NFL prediction quality from source search.

## Clean natural-language benchmark: measured failure (October 23, 2026)

**Status: NO-GO for XERJ source navigation as currently queried. Do not promote into agent defaults or NFL production paths.**

The user-provided local comparison report is for repo commit
`c9f31a227ba0a6b47f9eb0943987d567f3197aad`, source fingerprint
`3b4125e280ec9270d7ba1e8b32e461eee6974c18362ba81f3603de7afb66f6d2`,
20 tasks, k=5, suite `natural_language_queries_v1.json`. This fixed source fingerprint identifies the **evaluated** commit, not the subsequently modified diagnostic code.

| Strategy | Hit@5 | MRR@5 | Query p50 | Notes |
| --- | ---: | ---: | ---: | --- |
| XERJ lexical body match, raw | 4/20 (0.20) | 0.1125 | 6.41 ms | Clean index, correct source identity |
| XERJ lexical, pool 30 + owner/dedupe | 5/20 (0.25) | 0.1267 | 23.35 ms API; 0.01 ms local ranking | Gains one task; regresses zero |
| Independent rg + BM25/path/owner | 16/20 (0.80) | 0.4850 | 47.4 ms | Local catalog build 274.63 ms |

The ranker found the expected owner on `nl-16-copilot-boundary` at position 5 (a deduplication gain), and improved checkout-doctor from rank 4 to 3. All five XERJ owner-ranked hits were also retrieved by rg. The extra owner-ranked 30-candidate pool found an expected file on 13/20 questions, so **65% candidate recall puts an upper bound below the target 80% Hit@5 even for a perfect reranker**. Eleven of the twenty questions succeeded for rg but missed for owner-ranked XERJ. All top-five raw results matched across the requests with sizes 5 and 30.

The source-owner heuristic is intentionally invoked only on exact identifier-like queries; for ordinary sentences, its improvement is deduplication, not semantic understanding. Latency is not apples-to-apples: the rg catalog's build cost and XERJ's separate indexing/server startup are not included in both per-query medians. The small, curated suite is directional rather than a statistically broad developer productivity estimate. It does not assess code-line relevance, downstream agent completion, model quality, or fantasy outcomes.

### Next diagnostic experiment, not a retroactive pass

Official XERJ documentation describes three distinct query families: lexical `match`, server-side `semantic` on fields mapped `semantic_text`, and `hybrid` rank fusion. The pilot previously exercised **only** `match` against the `body` field. New opt-in `--query-mode` variants let us measure whether the retrieval API used was the bottleneck. They never alter index data, production projection paths, expected answer labels, or the existing lexical control.

**Before using semantic or hybrid**, inspect `xerj autoindex map --url http://127.0.0.1:9200`. The relevant code indices must expose `body` with compatible semantic mapping. If not, report that these query modes are unsupported by this index and do **not** silently fall back to lexical or delete/rebuild unrelated indices. XERJ's default local embedder is described by its documentation as deterministic/lexical, not a large neural embedding model. A query failure is evidence of a mapping or implementation incompatibility, not a quality score.

From the repository root, with the existing clean index and matching receipt for current HEAD:

    python scripts/xerj_pilot.py prepare
    python scripts/xerj_pilot.py index
    python scripts/xerj_pilot.py index --apply

For each mode (`semantic` then `hybrid`), keep queries, k, corpus and answer labels unchanged; run raw and owner-deduplicated reports:

    python scripts/xerj_pilot.py benchmark \
      --query-mode semantic \
      --cases configs/xerj/natural_language_queries_v1.json \
      --output .xerj-reports/natural_semantic_raw.json
    python scripts/xerj_pilot.py benchmark \
      --query-mode semantic --ranker symbol-owner --candidate-pool 30 \
      --cases configs/xerj/natural_language_queries_v1.json \
      --output .xerj-reports/natural_semantic_owner.json
    python scripts/xerj_compare.py \
      --raw .xerj-reports/natural_semantic_raw.json \
      --owner .xerj-reports/natural_semantic_owner.json \
      --rg .xerj-reports/natural_rg.json \
      --output .xerj-reports/natural_semantic_comparison.json

Repeat the commands with `--query-mode hybrid` and distinct `natural_hybrid_*.json` filenames. The report checker refuses to compare two different XERJ query modes in one paired report.

Treat these reruns on the **already inspected natural-language test set as exploratory diagnostics only**. An eventual go decision requires preregistering a fresh holdout of independently written engineering questions, validating file ownership, and demonstrating value beyond rg without compromising source provenance or existing CI. No acceptance criteria should be retuned to make the existing benchmark pass.
