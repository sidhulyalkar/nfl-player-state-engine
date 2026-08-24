# 2026 Shadow Season

## Purpose

The 2026 Shadow Season is the live evidence bridge between historical backtests and production authority.

It records exactly what the system knew at fixed weekly checkpoints, preserves the production direct-player quantile forecast, records research challengers beside it without changing decisions, and settles realized outcomes later in a separate immutable companion record.

The shadow ledger is evidence. It does not promote a model by itself.

## Authority

Production player-outcome authority remains the direct player quantile model.

The Player State Graph and any future challenger remain `research_only` inside shadow records. A challenger may be evaluated against the same realized player-week, but the shadow recorder cannot alter production q10/q50/q90, production recommendations, or model authority.

Settlement is `evaluation_only`. It never edits the original forecast checkpoint.

## Weekly checkpoints

The protocol recognizes four named checkpoints:

1. `WEDNESDAY`
2. `FRIDAY`
3. `SUNDAY_PREGAME`
4. `FINAL_DECISION`

The names are semantic operating checkpoints rather than hard-coded clock times. Every invocation must supply an explicit UTC-aware `prediction_cutoff`.

This matters because NFL schedules include Thursday, Saturday, Sunday, and Monday games, and because a fixed wall-clock Sunday timestamp would not be a valid cutoff for every player-week.

## No-hindsight contract

A checkpoint is valid only when every timestamped source in the snapshot satisfies:

```text
source.available_at <= prediction_cutoff
```

A later source is rejected.

Decision context containing hindsight fields such as `actual`, `realized`, `regret`, `outcome`, or `settled` is rejected.

The recorder copies only an allow-listed production forecast schema. Final outcomes present elsewhere in a source table are not serialized into the live checkpoint.

Production quantiles must be finite and ordered:

```text
q10 <= q50 <= q90
```

Conflicting populated projection aliases fail closed instead of silently choosing one.

## Deterministic checkpoint identity

One checkpoint identity is derived from:

```text
season
week
checkpoint
league_key
prediction_cutoff
```

The resulting `snapshot_id` does not depend on refresh time.

That gives refreshes the correct semantics:

- identical retry: idempotent;
- same checkpoint identity with different content: immutable conflict;
- new cutoff or checkpoint: new evidence record.

Each JSON record also carries a SHA-256 digest of its canonical content. Local tampering is therefore detectable before the record is read or settled.

## Snapshot contents

A snapshot contains:

- season, week and checkpoint;
- exact prediction cutoff and capture time;
- league key when applicable;
- input source names, artifact hashes and availability times;
- model metadata;
- safe point-in-time decision audit context;
- one row per player with production q10/q50/q90;
- production availability/reliability/decision fields when available;
- optional Player State Graph q10/q50/q90 and role context;
- explicit authority fields showing that the challenger is research-only.

No realized outcome belongs in this file.

## Settlement

After the player-week is complete, run settlement against a realized outcome table.

The settlement record stores:

- the immutable `snapshot_id`;
- the original snapshot SHA-256;
- realized player outcomes;
- settlement source SHA-256;
- completion/missing-player diagnostics;
- production and challenger metrics.

Strict settlement requires an actual for every player in the checkpoint. Partial settlement is possible only through the explicit `--allow-partial` operator flag.

An existing settlement cannot be replaced by a later one with different values. Corrections therefore require an explicit future schema/versioning decision rather than silent mutation of historical evidence.

## Live metrics

For production and challenger distributions independently, settled evidence reports:

- q50 MAE;
- q10/q50/q90 pinball loss;
- mean pinball loss;
- 80% interval coverage;
- mean interval width;
- empirical CDF calibration at q10/q50/q90.

The store aggregates these metrics overall, by checkpoint, and by position.

These are descriptive live-shadow metrics. They do not constitute an automatic promotion policy.

## Operator workflow

### Record a checkpoint

```bash
python scripts/record_shadow_checkpoint.py \
  --projections artifacts/predictions/product_player_values.csv \
  --season 2026 \
  --week 1 \
  --checkpoint WEDNESDAY \
  --prediction-cutoff 2026-09-09T18:00:00Z \
  --projection-available-at 2026-09-09T17:50:00Z \
  --challenger artifacts/player_state_graph/player_state_graph_summaries.parquet \
  --challenger-available-at 2026-09-09T17:45:00Z
```

The operator hashes the production and challenger artifacts automatically.

Additional timestamped inputs can be supplied through `--source-manifest`. A manifest must contain a `sources` list of objects with `name` and, when known, `available_at`, `sha256`, `path`, and/or `source_url`.

### Settle a checkpoint

```bash
python scripts/settle_shadow_checkpoint.py \
  --snapshot-id <snapshot_id> \
  --actuals data/processed/week_01_actuals.parquet \
  --actual-column fantasy_points_ppr
```

The actuals file is hashed and stored only in the settlement companion.

## API

The operational API exposes read-only endpoints:

```text
GET /v1/model/shadow-season?season=2026
GET /v1/model/shadow-season/health?season=2026
GET /v1/model/shadow-season/snapshots?season=2026&week=1&checkpoint=WEDNESDAY
GET /v1/model/shadow-season/snapshots/{snapshot_id}
```

There is intentionally no HTTP write endpoint for shadow history.

## Artifact layout

```text
artifacts/shadow_season/
  snapshots/
    2026/
      week_01/
        WEDNESDAY/
          <snapshot_id>.json
        FRIDAY/
        SUNDAY_PREGAME/
        FINAL_DECISION/
  settlements/
    <snapshot_id>.json
```

## Evidence ladder

The shadow season is primarily Tier 4 evidence in the Player State Graph evidence ladder: live shadow-season performance under real publication-time constraints.

It can also support the later Tier 5 question when paired with frozen decisions: did a challenger or decision policy improve actual decision value?

Those are distinct claims. Better live pinball loss or interval coverage is not automatically equivalent to better draft, waiver, trade, lineup, playoff, or championship outcomes.

## What this does not do

The shadow ledger does not:

- change the production champion;
- infer post-hoc injury/news state into earlier checkpoints;
- repair old forecasts after results are known;
- replace the historical Evidence Factory;
- turn scenario sensitivity into a calibrated forecast;
- convert Player State Graph disagreement into a production override;
- claim decision value from forecast metrics alone.

Its job is narrower and more valuable: create trustworthy live evidence that future model and decision-system promotion arguments can actually stand on.
