# Model Performance Showcase

The Performance Scoreboard is a **read-only evaluation lane** for comparing frozen Player State Engine weekly forecasts against frozen expert evidence and completed fantasy outcomes.

It exists to answer a deliberately uncomfortable question every week:

> Did the model actually help, or did the experts read the week better?

The showcase is not a promotion mechanism, not a fallback projection source, and not a new decision model. Every API response declares:

```text
authority=evaluation_only
may_change_production_decisions=false
```

## Scientific contract

A weekly comparison has three independent snapshots:

1. **model snapshot**: the Player State Engine forecast frozen before the games being evaluated;
2. **expert snapshot**: point-in-time expert evidence, normally FantasyPros ECR through the maintained official API client;
3. **actuals snapshot**: completed player outcomes scored under the exact fantasy `LeagueConfig` being evaluated.

Every snapshot records a timezone-aware capture timestamp and a source label. The immutable showcase artifact hashes the normalized input rows plus those provenance fields, so a changed model, expert snapshot, scoring context, timestamp, or outcome produces a different artifact identity.

Do not replace an older snapshot in place to improve a result. Build a new artifact and let both identities remain auditable.

## Rank semantics

FantasyPros ECR is primarily an **ordinal ranking baseline**. It is not silently converted into a fantasy-point projection.

The default weekly comparison therefore requires a comparable **position rank** such as FantasyPros `position_rank` and compares it with:

- model rank within position;
- actual finish rank within position.

Never compare overall ECR directly with a positional actual rank. A value such as overall WR18 and WR3 are different ranking spaces even when both contain the word `rank`.

If a frozen expert source separately publishes actual projected fantasy points, those points may be supplied explicitly. Only then does the weekly battle add expert point MAE/RMSE and allow fantasy-point MAE to become the primary head-to-head metric.

## Core metrics

Each artifact calculates, when supported by the inputs:

- model fantasy-point MAE, RMSE, and bias;
- expert fantasy-point MAE, RMSE, and bias when expert points are present;
- model and expert positional rank MAE;
- rank correlation diagnostics;
- QB top-12 hit rate;
- RB top-24 hit rate;
- WR top-36 hit rate;
- TE top-12 hit rate;
- q10/q90 80% interval coverage and mean width when model tails are present;
- per-player model error, expert rank error, and model edge versus expert rank error;
- position-by-position weekly winners.

The weekly headline uses fantasy-point MAE only when both model and expert point projections exist. Otherwise it uses positional rank MAE. Missing expert points are reported as unavailable rather than imputed from ECR.

## Artifact layout

Artifacts live under:

```text
artifacts/evaluation/showcase/<SEASON>/week_<WW>/<ARTIFACT_ID>/
```

Each immutable artifact contains:

```text
manifest.json
model_snapshot.parquet
expert_snapshot.parquet
actuals.parquet
player_deltas.parquet
weekly_metrics.json
narrative_summary.json
```

The week directory also contains `latest.json`, a small mutable convenience pointer to the most recently built artifact. The content-addressed artifact directory is the evidence identity.

Generated showcase artifacts are intentionally ignored by Git. Store important season evidence in durable artifact/object storage rather than turning source control into a data warehouse.

## Capture a weekly FantasyPros ECR snapshot

With `PSE_FANTASYPROS_API_KEY` configured on the server or operator machine:

```bash
python scripts/fetch_fantasypros_rankings.py \
  --season 2026 \
  --week 1 \
  --position ALL \
  --scoring PPR \
  --output-root data/external/rankings/fantasypros
```

The filename contains the capture timestamp. Preserve that exact file for evaluation. The normalized output includes `position_rank`, which is the preferred showcase ranking field.

This is separate from live ADP. ADP remains a draft-timing market signal and must not be relabeled ECR or weekly projection accuracy.

## Build exact weekly actuals

Once the week is complete, score the player-week statistics under the exact league scoring contract:

```bash
python scripts/build_weekly_actuals.py \
  --stats data/raw/nflverse/player_stats.csv \
  --league-config configs/fantasy/8_team_ppr_2qb_expanded.yaml \
  --season 2026 \
  --week 1 \
  --output artifacts/evaluation/inputs/2026_week01_ppr_actuals.parquet
```

The script uses the maintained `LeagueConfig` and `score_fantasy_stats` boundary. It prints the scoring-contract ID so the evaluation can be tied back to the exact scoring operation.

For the two half-PPR roster constructions, player scoring is the same contract even though replacement economics differ. Weekly forecast evaluation should therefore not create a fake third scoring model merely because one league starts two quarterbacks.

## Build the immutable weekly showcase

Example:

```bash
python scripts/build_weekly_showcase.py \
  --model artifacts/predictions/2026_week01_ppr_frozen.parquet \
  --expert data/external/rankings/fantasypros/2026_w01_ppr_unknown_all_ecr_<TIMESTAMP>.parquet \
  --actuals artifacts/evaluation/inputs/2026_week01_ppr_actuals.parquet \
  --season 2026 \
  --week 1 \
  --scoring ppr \
  --model-captured-at 2026-09-10T16:00:00+00:00 \
  --expert-captured-at 2026-09-10T16:05:00+00:00
```

The builder auto-detects common q50/q10/q90 model columns and exact actual-points columns. It intentionally does **not** auto-select overall expert ECR as a positional baseline. The expert input must expose a comparable position-rank column unless `--expert-rank-column` explicitly selects another already-comparable positional field.

If an expert source publishes point projections in a separate column, pass:

```text
--expert-points-column <COLUMN>
```

No expert point column means rank-only head-to-head scoring, not failure.

## API

The operational API exposes:

```text
GET /v1/model/showcase
GET /v1/model/showcase/{season}
GET /v1/model/showcase/{season}/weeks/{week}
```

The week endpoint supports:

```text
?position=QB
?limit=100
?artifact_id=<EXACT_ARTIFACT_ID>
```

The default week request resolves `latest.json`. Supplying `artifact_id` reads a specific immutable comparison.

## Frontend

Open:

```text
http://localhost:3000/?workspace=showcase
```

The Performance Scoreboard includes:

- weekly winner and season record;
- positional rank-error and optional fantasy-point MAE battles;
- QB/RB/WR/TE round winners;
- season trend bars;
- model-versus-actual point scatter;
- best calls and biggest misses;
- position-filterable player receipts;
- immutable artifact ID and scoring metadata.

If no artifact exists, the page displays an explicit empty state. It never manufactures demo evaluation wins.

## What this does not do

The showcase cannot:

- move or derive a champion pointer;
- modify production projection bytes;
- train or retrain a model;
- change a scoring contract;
- change Draft-Day Doctor readiness;
- overwrite live ADP or K/DST authority;
- feed expert rankings into the production model merely because experts won a week;
- promote a challenger because it produced a prettier chart.

A weekly expert win is evidence to investigate, not permission to mutate production. Likewise, a model win is not proof that every feature or uncertainty claim is calibrated.

## Recommended weekly ritual

Before kickoff, archive:

- the exact model forecast used for decisions;
- the exact expert snapshot you want to grade against;
- capture timestamps and scoring contract.

After games complete:

- acquire the completed nflverse player-week rows;
- build exact league-scored actuals;
- build the immutable showcase artifact;
- inspect position battles, calibration, best calls, and misses;
- look for persistent multi-week patterns before changing models.

Football is exceptionally talented at generating one-week stories. The scoreboard is designed to accumulate receipts until those stories become evidence.
