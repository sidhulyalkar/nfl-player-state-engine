# Draft Market Data Archive

## Purpose

This layer creates the immutable inputs required by the empirical draft-market evaluator.

It intentionally separates three different objects:

1. **draft outcomes**: what actually happened in a Sleeper draft;
2. **market snapshots**: what an external ranking/ADP source published before that draft;
3. **training observations**: the as-of join used by the survival model.

Actual draft order must never be reused as a proxy for pre-draft ADP.

## Sleeper outcome archive

Sleeper's public read-only API exposes historical user drafts, draft metadata, and complete picks. Archive raw responses before normalization.

Each archived draft directory contains:

```text
draft.json
picks.json
traded_picks.json
manifest.json
```

The manifest records retrieval time, source URLs, byte counts, SHA-256 hashes, draft ID, league ID, season, status, and draft start time.

Existing files are immutable by default. A second retrieval of the same draft verifies the existing bytes and refuses to overwrite a mismatch unless the operator explicitly chooses a separate refresh destination.

## Normalized outcome table

Normalization emits one row per realized pick with at least:

```text
draft_id
league_id
season
draft_started_at
actual_pick
round
draft_slot
picked_by
roster_id
platform_player_id
player_name
position
nfl_team
teams
scoring
qb_slots_per_team
superflex_slots_per_team
starter_slots_per_team
source
source_retrieved_at
```

No football outcome or market-ranking field is manufactured here.

## Market snapshots

Market snapshots are independent timestamped artifacts. Existing `fetch_fantasypros_rankings.py` can capture FantasyPros ADP/ECR snapshots. Other sources may enter only through the same explicit snapshot contract.

A normalized market snapshot needs:

```text
source
captured_at_utc
source_player_id or canonical identity
player_name
position
rank / ADP
rank_std or ADP dispersion when available
scoring
format metadata when actually certified by the source
```

Requested league settings are not treated as source-certified format metadata when the upstream response does not certify them.

## As-of join

For each historical draft, market evidence must satisfy:

```text
market_snapshot_at <= draft_started_at
```

The join chooses the latest compatible snapshot before the draft. It never uses a later snapshot and never substitutes the realized pick number when no valid snapshot exists.

Rows without a valid market snapshot remain unmatched and are reported. Strict training can only use rows whose point-in-time market evidence is verified.

## Identity

Prefer explicit platform or canonical player IDs. Name matching is a controlled fallback only when both sides lack stronger identity, and ambiguous normalized names fail closed.

Cross-platform market sources should preserve both source identity and canonical identity whenever available.

## Authority

This archive is evidence plumbing, not model evidence.

Successful API retrieval, normalization, or as-of joining does not promote the empirical draft-market model. Model authority remains governed by the chronological evaluator and downstream frozen decision replay.
