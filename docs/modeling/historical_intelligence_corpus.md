# Historical Intelligence Corpus

## Purpose

The historical intelligence corpus is the evidence-input bridge between the repository's existing historical source reconstruction and the Structured Intelligence ablation laboratory.

It answers a question that ordinary feature tables cannot:

> For each historical player-week, which official source was actually observed before the frozen prediction cutoff, and what specific evidence was available at that time?

The corpus is research evidence only. It does not activate an intelligence family, does not change the production quantile champion, and does not promote a model.

## Three separate artifacts

The corpus intentionally separates three concepts.

### 1. Evidence

`official_evidence.parquet` contains typed `OfficialAvailabilityEvidence` rows selected strictly before each player-game cutoff.

For archived injury reports, the builder retains the latest eligible player status before cutoff and emits separate practice-participation and game-designation events.

For optional timestamped depth charts, the builder retains the latest eligible player depth snapshot before cutoff and rejects snapshots older than the configured maximum age.

Late records are never moved backward in time.

### 2. Source coverage

`source_coverage.parquet` is keyed by `season`, `week`, and `player_id` and contains explicit source-observation flags.

The critical distinction is:

```text
source covered != player has a claim
```

For injury reports, a player with no row is considered source-covered only when at least one timestamped report row proves that the relevant team-week report was observed before the game cutoff.

This means:

- teammate has no injury row + team report observed -> covered, no player claim;
- no team report observed -> not covered, unknown;
- player claim found -> covered plus claim prevalence.

The evaluator can therefore distinguish "observed and not listed" from "source never observed".

For timestamped depth charts, source coverage requires a team snapshot before cutoff that is no older than the configured staleness limit.

### 3. Evidence provenance

`evidence_provenance.json` uses the same `IntelligenceEvidenceProvenance` contract consumed by the structured-intelligence ablation operator.

Tier-2 (`MULTI_SEASON_ISOLATED`) requires all of the following:

- at least two source-covered historical seasons;
- point-in-time schedule cutoffs for the full evaluation panel;
- a verified immutable evidence archive;
- a deterministic archive identity;
- point-in-time source-coverage construction.

If checksum verification is unavailable or fails, the corpus cannot self-declare Tier 2. The explicit `--allow-unverified-archive` option is research-only and leaves the resulting provenance below Tier 2.

## Frozen source identity

The corpus verifies archived evidence files against `SOURCE_MANIFEST.csv` by SHA-256.

The final frozen identity also includes:

- the schedule file SHA-256;
- a recursive SHA-256 digest of the frozen benchmark root;
- the materialized evidence rows;
- the materialized source-coverage rows.

Changing the source archive, kickoff schedule, frozen benchmark panel, evidence selection, or coverage construction therefore changes the frozen sample identity.

## Injury-data boundary

The nflverse historical injury source is treated as certified only through the 2024 season in this corpus builder.

The operator fails closed if post-2024 rows are presented as nflverse historical injury evidence. 2025+ official injury availability must come from a separately archived prospective official source with its own timestamps and checksum manifest.

This is intentional. Missing post-2024 injury files must never become an implicit healthy-player signal.

Timestamped 2025+ depth charts may still be evaluated as a distinct optional official source when their snapshot timestamps satisfy the frozen cutoff and staleness rules.

## Build the corpus

First acquire the historical source archive and preserve its manifest:

```bash
python scripts/acquire_historical_sources.py \
  --seasons 2021 2022 2023 2024
```

Then build the frozen official corpus:

```bash
python scripts/build_historical_intelligence_corpus.py \
  --data-dir data/raw/historical_sources \
  --benchmark-root artifacts/reports/benchmark_real \
  --schedules data/raw/nflverse_full/schedules.parquet \
  --seasons 2021 2022 2023 2024 \
  --output-dir artifacts/intelligence_corpus/historical_official
```

To add timestamped depth charts as an explicit second source family:

```bash
python scripts/build_historical_intelligence_corpus.py \
  --data-dir data/raw/historical_sources \
  --benchmark-root artifacts/reports/benchmark_real \
  --schedules data/raw/nflverse_full/schedules.parquet \
  --seasons 2021 2022 2023 2024 \
  --include-depth-charts \
  --depth-maximum-age-days 14 \
  --output-dir artifacts/intelligence_corpus/historical_official_with_depth
```

## Output bundle

```text
artifacts/intelligence_corpus/historical_official/
  official_evidence.parquet
  source_coverage.parquet
  evidence_provenance.json
  corpus_audit.json
  run_manifest.json
  ledger/
    claims/...
```

`run_manifest.json` records input hashes, archive-verification failures, operator settings, evidence tier, corpus audit statistics, ledger health, and output hashes.

## Feed the corpus into the ablation laboratory

The corpus is designed to plug directly into PR #25's research operator:

```bash
python scripts/run_structured_intelligence_ablation.py \
  --features data/processed/weekly_features_with_objective_context.parquet \
  --ledger-root artifacts/intelligence_corpus/historical_official/ledger \
  --source-coverage artifacts/intelligence_corpus/historical_official/source_coverage.parquet \
  --evidence-provenance-manifest artifacts/intelligence_corpus/historical_official/evidence_provenance.json \
  --target fantasy_points_ppr \
  --output-dir artifacts/intelligence_ablations/historical_official
```

A Tier-2 corpus only certifies the **input evidence sample**. The model family must still clear the ablation laboratory's paired effect, confidence interval, FDR, consistency, calibration, identity-control, and coverage gates.

Even then, the result is only eligible for manual activation review. Production activation remains a separate authority decision.

## Initial experimental sequence

The first real experiment should remain deliberately narrow:

1. Build the 2021-2024 injury-only corpus.
2. Inspect source coverage by season, week, team, and position before looking at predictive metrics.
3. Run the official-availability rung against the frozen numerical baseline.
4. Inspect identity-shuffle and future-shift controls.
5. Inspect calibration and position-specific regressions.
6. Only after the injury-only result is understood, run a separately identified depth-chart augmentation ablation.
7. Keep structured news and public-player context prospective unless historical publication-time provenance can be independently proven.

This sequencing keeps chronology repair, source coverage, and feature-family expansion as separate scientific questions.