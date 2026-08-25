# Frozen historical intelligence experiment

This protocol closes the gap between the historical official-evidence corpus and the structured-intelligence ablation laboratory.

It answers a narrower and more defensible question than “did the old production model already know this?”:

> When the **current** leakage-safe feature/model code is replayed over the exact frozen historical out-of-sample player-week universe, does timestamp-safe official availability evidence add incremental predictive value beyond the numerical baseline?

The experiment remains research-only. It cannot enable an intelligence family or change production projections.

## Why a new replay layer is necessary

The frozen benchmark persisted predictions, outcomes, metrics, and a raw-data manifest. It did **not** persist the exact feature matrix used by the historical production run.

Therefore the repository must not claim a byte-for-byte historical production replay.

The new replay layer instead:

1. verifies the raw numerical source files against `artifacts/reports/benchmark_real/DATA_MANIFEST.json`;
2. rebuilds weekly features with the **current** `build_weekly_features()` implementation;
3. restricts the result to the exact player-game rows present in the frozen OOS benchmark;
4. verifies every rebuilt realized target against the frozen benchmark outcome;
5. attaches the exact schedule-derived `prediction_cutoff` from the frozen official-intelligence corpus;
6. attaches canonical official claims from the immutable structured-claim ledger;
7. joins source coverage from its separate hashed artifact;
8. runs the existing paired structured-intelligence staircase and negative controls.

The resulting baseline authority is explicitly:

```text
current_feature_builder_frozen_source_replay
```

and **not** `historical_production_parity`.

## Source-byte authority

A URL is not evidence identity.

`DATA_MANIFEST.json` records SHA-256 and byte counts for the raw benchmark sources. The replay requires those exact bytes for activation-review authority.

Use:

```bash
python scripts/acquire_frozen_benchmark_sources.py \
  --seasons 2021 2022 2023 2024
```

The acquisition operator:

- reuses an existing file only when SHA-256 **and** byte count match;
- downloads into a temporary file;
- verifies the temporary file before accepting it;
- refuses to overwrite a mismatched local file;
- rejects upstream bytes that no longer match the frozen manifest.

This matters especially for mutable raw URLs. If an upstream file has changed, the correct response is to recover the historical bytes or run an explicitly unverified research replay, not silently bless the new file.

A prior season of player statistics is included automatically when the manifest contains it so the first evaluation season has real lagged history.

## Build the official evidence corpus first

The official-intelligence corpus remains the authority for evidence timestamps and source coverage:

```bash
python scripts/build_historical_intelligence_corpus.py \
  --seasons 2021 2022 2023 2024
```

Its output root contains:

```text
artifacts/intelligence_corpus/historical_official/
  source_coverage.parquet
  evidence_provenance.json
  ledger/
  corpus_audit.json
  run_manifest.json
```

The replay never infers “healthy” from an absent player claim. Source coverage remains a separate team-week observation contract.

## Run the experiment

After the two source archives are present:

```bash
python scripts/run_historical_intelligence_experiment.py \
  --seasons 2021 2022 2023 2024 \
  --target fantasy_points_ppr
```

Default inputs are:

```text
artifacts/reports/benchmark_real/
data/raw/frozen_benchmark_sources/
artifacts/intelligence_corpus/historical_official/
```

The operator writes:

```text
artifacts/intelligence_ablations/historical_official/
  replay_features.parquet
  point_in_time_features.parquet
  incremental_evidence.csv
  benchmark_source_verification.json
  replay_audit.json
  experiment_audit.json
  run_manifest.json
  variants/
```

The manifest hashes every accepted numerical source, the frozen benchmark tree, source coverage, evidence provenance, and the immutable claim ledger.

## Hard gates before model fitting

The replay fails closed when:

- a required frozen numerical source is missing;
- a benchmark source SHA-256 or byte count differs, unless the operator explicitly requests an unverified research run;
- the current feature builder cannot reconstruct a frozen player-game row;
- a rebuilt realized target differs from the frozen benchmark outcome;
- source coverage lacks a schedule-derived prediction cutoff;
- the claim ledger fails integrity verification;
- the evidence provenance artifact is missing or invalid.

`--allow-unverified-benchmark-sources` is deliberately narrow. It can permit inspection of a hash-drifted source set, but the runner forcibly adds:

```text
frozen_numerical_baseline_sources_unverified
```

to every activation-review decision and sets `eligible_for_activation_review = false`.

Missing files are never bypassed.

## Interpretation

The official-availability row in `incremental_evidence.csv` is the primary result.

It retains the PR #25 gates:

- paired q10/q50/q90 pinball effect;
- season-week block-bootstrap interval;
- finite-sample p-value;
- run-wide Benjamini-Hochberg FDR;
- season, position, and week consistency;
- identity-shuffle negative control;
- shifted-time leakage sensitivity;
- overall and position calibration movement;
- minimum paired sample size;
- explicit source-coverage threshold;
- evidence-tier requirement.

A positive result means the family is eligible for **manual research review**, not automatic production activation.

A negative result is equally useful: it tells us that official availability, as encoded and timestamped, does not add enough incremental predictive value beyond the current numerical stack under the frozen protocol.

## Scientific boundary

This experiment intentionally separates four claims:

| Claim | Can this experiment establish it? |
|---|---|
| Official evidence was available before cutoff | Yes, when corpus provenance is verified |
| Raw numerical replay sources match the frozen benchmark manifest | Yes, when source verification passes |
| Current feature/model code benefits from official availability | Yes, subject to the statistical gates |
| Historical production feature matrix is reproduced byte-for-byte | **No**; that matrix was not persisted |

That last distinction is permanent unless an older exact feature artifact is recovered. The repository should preserve it instead of smoothing it away in prose.
