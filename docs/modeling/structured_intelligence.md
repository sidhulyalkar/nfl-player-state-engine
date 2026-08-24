# Structured Intelligence Evidence Contract

## Purpose

Structured Intelligence turns public football information into timestamped, auditable evidence without granting narrative text direct authority over production forecasts.

The repository already contains collectors and conservative extractors for official availability, structured news, and public player context. This layer defines the missing contract between extraction and modeling:

```text
public document
  -> typed extracted claim
  -> canonical provenance-preserving claim
  -> immutable claim ledger
  -> point-in-time evidence resolution
  -> frozen ablation / shadow evidence
  -> explicit manual feature activation
```

The default stopping point is evidence. Production use requires a separate promotion decision.

## Authority

Structured claims are `research_evidence_only` by default.

The direct player quantile model remains production authority. Existing official-availability, structured-news, and public-context features do not become production features merely because the code can calculate them.

The activation registry is fail-closed:

- `disabled`: evidence may be collected and analyzed, but cannot be materialized as model features;
- `shadow`: the family may participate in frozen experiments or live shadow evaluation, but cannot affect production decisions;
- `enabled`: requires explicit experiment, evidence-tier, reviewer, and approval-time metadata.

Automatic promotion is forbidden.

## Canonical claim

`StructuredClaim` preserves:

- player identity;
- claim type;
- domain and latent state;
- direction and magnitude;
- assertion/retraction/supersession status;
- decay half-life;
- full source provenance;
- optional correction linkage;
- canonical SHA-256 content digest.

The claim does not contain a production feature flag that can silently become true. Resolved evidence snapshots explicitly emit:

```text
production_feature_enabled = false
authority = research_evidence_only
```

## Required provenance

Every claim carries `ClaimProvenance` with:

- source URL;
- publisher type;
- evidence class;
- authored timestamp;
- collected timestamp;
- explicit availability timestamp;
- explicit availability basis;
- supporting evidence excerpt;
- extractor version;
- extractor confidence;
- source reliability;
- document ID/content hash when available;
- caveats.

All timestamps are normalized to UTC.

### Availability basis

A claim can use one of two explicit point-in-time conventions:

`collected`
: The claim becomes usable when this system actually collected it. This is the conservative live default.

`published`
: The claim becomes usable at the source's authored/published timestamp. This is only appropriate when a historical replay deliberately treats that timestamp as the availability contract.

The basis is stored in every claim. The code never silently substitutes published time for collection time.

## Evidence classes

The canonical layer preserves the existing news hierarchy:

1. `OFFICIAL`
2. `DIRECT_OBSERVATION`
3. `REPORTED`
4. `COACH_QUOTE`
5. `PLAYER_QUOTE`
6. `ANALYSIS`
7. `SPECULATION`

Evidence class changes weighting in research resolution, but it does not turn a claim into truth.

## Contradictions

Conflicting sources are preserved rather than merged with last-write-wins semantics.

For each player and latent state, the as-of resolver reports:

- weighted consensus signal;
- support strength;
- source count;
- high-authority claim count;
- speculation count;
- positive support;
- negative support;
- `conflict_score`.

`conflict_score` ranges from 0 to 1:

- `0`: weighted evidence lies on one side;
- `1`: positive and negative weighted support are equally balanced.

A conflict score is a disagreement diagnostic, not a calibrated probability.

## Corrections and retractions

Historical evidence is never rewritten retroactively.

A correction may reference `supersedes_claim_id`.

- Before the correction's `available_at_utc`, historical queries still see the original assertion.
- After the correction becomes available, the original assertion is suppressed.
- A retraction can remove the earlier claim without adding a replacement.
- A new asserted claim can supersede the earlier claim and become the active evidence.

The ledger still retains all physical records for auditability.

## Immutable claim ledger

`StructuredClaimLedger` stores one JSON file per canonical claim ID.

Behavior:

- identical retries are idempotent;
- a changed payload under an existing claim ID is rejected;
- canonical SHA-256 is verified before persistence and on every read;
- local tampering causes read/health failure;
- queries can filter by player, domain, and point-in-time cutoff.

Default root:

```text
artifacts/structured_intelligence/
  claims/
    <claim-id-prefix>/
      <claim-id>.json
  snapshots/
  run_manifest.json
```

## Structured news operator

Build the canonical structured-news ledger from an archived `PublicDocument` JSONL file:

```bash
python scripts/build_structured_intelligence_ledger.py \
  --documents data/external/intelligence/documents.jsonl \
  --as-of 2026-09-09T18:00:00Z \
  --availability-basis collected \
  --output-root artifacts/structured_intelligence
```

The operator:

1. hashes the source document archive;
2. runs the existing conservative news extractor;
3. converts extracted `NewsClaim` objects into canonical structured claims;
4. persists claims immutably;
5. resolves only claims available at the requested cutoff;
6. writes an evidence snapshot;
7. records ledger health and activation state in `run_manifest.json`.

It never enables an intelligence feature family.

## Activation registry

`IntelligenceActivationRegistry` covers four families:

```text
official_availability
objective_opportunity
structured_news
public_player_context
```

Missing registry files behave as an all-disabled registry.

An `enabled` family must provide:

- evidence tier;
- experiment ID;
- manual approver identity/label;
- approval timestamp.

This metadata proves that activation was deliberate. It does not prove the experiment was scientifically correct, so promotion decisions must still follow the repository's frozen evaluation protocol.

## Relationship to the 2026 Shadow Season

The shadow-season ledger records what the production and challenger systems predicted at fixed checkpoints.

Structured Intelligence provides timestamped evidence that can later be attached to those checkpoints as a source family. The correct sequence is:

```text
structured claim available before cutoff
  -> frozen shadow evidence snapshot
  -> model/challenger consumes only if its family authority permits it
  -> immutable prediction checkpoint
  -> realized outcome settlement later
```

No source published or collected after the prediction cutoff may be backfilled into the checkpoint.

## Required experiments before activation

For each feature family, the minimum scientific path is:

1. define a frozen historical or prospective sample;
2. report source coverage and identity resolution;
3. compare against the current production champion and simpler baselines;
4. inspect calibration by position/season;
5. run negative controls, including identity/time perturbations where applicable;
6. report data availability and contradiction rates;
7. control multiple comparisons when several feature families are tested;
8. require explicit manual promotion metadata.

For structured news specifically, the first useful experiment is not “does news sound predictive?” It is:

> Does timestamped structured news improve participation/opportunity or fantasy-point distributions beyond official availability and objective opportunity, without degrading calibration under frozen point-in-time replay?

## Public player context boundary

Public player-context/persona signals remain more restricted than football news.

Permitted signals are observable football-context features such as training emphasis, recovery discussion, leadership language, team orientation, matchup specificity, and explicit role expectations.

They are not psychological truth, sensitive-trait inference, clinical diagnosis, private-life inference, or motivation scoring.

Public player context stays disabled until it independently clears a frozen ablation after stronger objective/official evidence families have been evaluated.

## Non-goals

This layer does not:

- scrape behind authentication or anti-bot challenges;
- treat social engagement as football truth;
- let an LLM silently reconcile contradictory reporting;
- infer medical diagnoses from public language;
- overwrite historical claims after corrections;
- promote a feature because it improves one aggregate metric;
- bypass the Evidence Factory or 2026 live shadow protocol;
- give narrative evidence direct production authority.

Its job is narrower: make football information testable, timestamped, reversible through explicit corrections, and scientifically accountable.
