# XERJ local pilot for NFL Player State Engine

**Status:** optional developer search experiment, not a fantasy model input or production dependency. XERJ is a local-first code/document search engine with a separate MCP server. Our goal is to see whether source retrieval helps agents find the real implementation and its boundaries.

## Hypothesis and scope

Index NFL Player State Engine source and documentation first, then compare retrieval against normal repository navigation on twenty preregistered engineering tasks. If useful, repeat using distinct namespaces for neurOS and MindForge, without mixing corpus content or allowing reference code to override project tests.

## Security contract

The script at scripts/xerj_pilot.py prepares a **committed-HEAD-only** mirror in ~/.cache/nfl-pse-xerj/corpus. It never copies untracked or modified working-tree content. Only explicitly selected src/, scripts/, docs/, tests/, configs/, and frontend code plus root guides are eligible. It excludes data/, artifacts/, private league snapshots, credentials, hidden files, binaries, lockfiles, symlinks, and oversized files. Several known credential patterns abort staging.

These rules are **defense in depth**, not a guarantee that no secret has ever been committed. Review snapshot_manifest.json before indexing. This manifest, kept in the parent of the corpus, records HEAD, source paths, SHA-256 hashes and byte sizes. All generated local reports are gitignored.

XERJ's node storage must stay outside both corpus and checkout (for example ~/.local/share/nfl-pse-xerj/node); otherwise a search engine can index its own storage. The dedicated index prefix is nfl-pse, never the default ax. Never delete unrelated indexes to resolve a prefix collision.

An XERJ node launched with --insecure has no TLS or API authentication; only use it bound to 127.0.0.1 on a trusted computer. The pilot wrapper rejects nonloopback endpoints. An authenticated local node is also supported using XERJ_API_KEY in the environment, never in repository files or command arguments.

**Invariant:** XERJ helps find code. It may not directly modify projection, model promotion, source-cutoff checks, league scoring, production readiness, or any fantasy decision. The Python API remains authoritative, and negative controls/frozen evaluations remain mandatory.

## Setup

Install and verify the XERJ executable from the official project: https://github.com/xerj-org/xerj . The verified CLI reference is https://www.xerj.org/docs/cli .

On macOS/Linux (for Windows PowerShell use equivalent paths and a terminal for the XERJ server):

Terminal A:

    mkdir -p "$HOME/.local/share/nfl-pse-xerj/node"
    xerj --insecure --data-dir "$HOME/.local/share/nfl-pse-xerj/node"

Terminal B, from a clean NFL Player State Engine checkout:

    python scripts/xerj_pilot.py prepare
    python scripts/xerj_pilot.py index
    # Inspect the dry-run plan and ~/.cache/nfl-pse-xerj/snapshot_manifest.json
    python scripts/xerj_pilot.py index --apply
    xerj autoindex map --url http://127.0.0.1:9200
    xerj search --url http://127.0.0.1:9200 --prefix nfl-pse -k 5 "assess_draft_release_readiness"
    python scripts/xerj_pilot.py benchmark

The first index command is a **dry-run by default**. Only --apply writes the index. A successful apply writes a local index_receipt.json alongside snapshot_manifest.json, recording the source fingerprint, prefix, local node URL, and complete/partial indexing status. A benchmark refuses an absent or stale receipt. When XERJ reports skipped/junk files, the receipt records partial, and coverage must be inspected before claiming completeness. The benchmark report appears under .xerj-reports/pilot_report.json and is not committed. Each source snapshot is keyed to one Git HEAD; repeat prepare and index when you commit new changes. Dirty changes are intentionally invisible.

If using an authenticated node, omit --insecure and export XERJ_API_KEY from its locally generated admin key. The autoindex client does not load that key from the server TOML automatically.

## Agent host / MCP integration

After starting the node, the official CLI provides:

    xerj init

Or point your local host's stdio MCP configuration to command xerj and args ["mcp", "--url", "http://127.0.0.1:9200"]. Store configuration outside the repository. The MCP command does not start a node on its own.

Agents should use prefix nfl-pse and return the exact ax_path, XERJ locator or line (when actually present), and the manifest's Git SHA. Open the real source and related tests before editing. If an indexed file differs from HEAD, re-run staging and indexing.

## What the benchmark measures

configs/xerj/pilot_queries.json contains twenty fixed tasks with query text and ground-truth source paths. The wrapper sends lexical match queries to the XERJ body field, scoped to nfl-pse-*, and records:

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
