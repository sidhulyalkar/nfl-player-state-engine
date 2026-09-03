# Weekly Performance Evidence Automation

The weekly performance automation turns the Model Performance Showcase into a repeatable evidence program rather than a manual post-game ritual.

It deliberately reuses the **Shadow Season** as the model forecast ledger. The model is not frozen once for the Shadow Season and again for the Scoreboard. One verified shadow checkpoint is the no-hindsight model receipt for both systems.

## Authority boundary

The workflow is evaluation infrastructure only.

It cannot:

- move a production champion pointer;
- modify production projection bytes;
- retrain or promote a model;
- change a league scoring contract;
- change Draft-Day Doctor readiness;
- feed FantasyPros rankings into production decisions.

The chain is:

```text
weekly production forecast
        |
        v
immutable Shadow Season checkpoint
        |
        +---- frozen FantasyPros ECR
        |
        v
retained weekly capture artifact
        |
        +---- completed nflverse player stats
        +---- exact LeagueConfig scoring
        |
        v
content-addressed Performance Scoreboard artifact
```

## GitHub Actions workflow

The reusable/operator workflow is:

```text
.github/workflows/weekly-model-performance.yml
```

A separate pull-request gate validates the automation surface:

```text
.github/workflows/weekly-model-performance-contract.yml
```

### Scheduled expert archive

At 20:17 UTC every Wednesday during January and September through December, the workflow resolves the nearest unstarted regular-season week from the current nflverse schedule and archives FantasyPros ECR for:

- `PPR`
- `HALF`

The archive is a no-op when `PSE_FANTASYPROS_API_KEY` is not configured. It never invents or substitutes rankings.

Artifacts are named:

```text
weekly-expert-ecr-<season>-w<week>-ppr
weekly-expert-ecr-<season>-w<week>-half_ppr
```

These snapshots exist so expert evidence is preserved before outcomes are known even when the weekly production forecast is published by a different job.

### Model capture

Model capture is intentionally driven by `workflow_call` or `workflow_dispatch` rather than a blind wall-clock cron. A forecast cannot be frozen until a real upstream model artifact exists.

The caller supplies:

- upstream Actions run ID;
- exact artifact name;
- optional relative projection path inside the artifact;
- season/week or schedule-resolved week;
- scoring lane;
- semantic Shadow Season checkpoint.

The capture job:

1. downloads the exact upstream Actions artifact;
2. records the artifact's GitHub `created_at` as a conservative availability timestamp;
3. obtains a frozen ECR snapshot, preferring a live official API capture and falling back to the retained Wednesday snapshot;
4. freezes one Shadow Season checkpoint with an explicit prediction cutoff;
5. verifies the Shadow Season's existing no-hindsight/source-timestamp contract;
6. stores the shadow snapshot, expert parquet and a chain manifest together.

The resulting retained artifact is:

```text
weekly-showcase-capture-<season>-w<week>-<scoring>
```

This is the object the settlement job looks for later.

### Automatic settlement

At 15:17 UTC every Tuesday during January and September through December, settlement resolves the latest fully elapsed regular-season week from nflverse.

It attempts both supported scoring lanes:

| Lane | Exact actual-scoring config |
|---|---|
| `ppr` | `configs/fantasy/8_team_ppr_2qb_expanded.yaml` |
| `half_ppr` | `configs/fantasy/12_team_half_ppr_median.yaml` |

For each lane, settlement:

1. finds the latest non-expired retained capture artifact for that week;
2. cleanly no-ops when no valid capture exists;
3. downloads current nflverse `stats_player_week_<season>.csv`;
4. freezes the requested regular-season week and hashes both the full source and week slice;
5. scores actual fantasy points with the exact `LeagueConfig`;
6. verifies and consumes the immutable Shadow Season checkpoint;
7. builds the content-addressed Performance Scoreboard artifact;
8. uploads the full capture + actuals + evaluation evidence chain for 120 days.

The completed artifact is named:

```text
weekly-showcase-evaluation-<season>-w<week>-<scoring>
```

## Schedule resolution

`scripts/resolve_showcase_week.py` uses the current nflverse games schedule.

For `capture`, it selects the nearest regular-season week whose first game date has not happened yet.

For `settle`, it selects the latest regular-season week whose final game date is already in the past.

An explicit `--week` always overrides inference. This makes manual reruns deterministic and prevents a clock-time heuristic from silently relabeling historical evidence.

## Direct Shadow Season consumption

`scripts/build_weekly_showcase.py` now supports:

```bash
python scripts/build_weekly_showcase.py \
  --shadow-snapshot artifacts/shadow_season/snapshots/2026/week_01/WEDNESDAY/<ID>.json \
  --expert data/external/rankings/fantasypros/<FROZEN_ECR>.parquet \
  --actuals artifacts/evaluation/inputs/2026_week01_ppr_actuals.parquet \
  --season 2026 \
  --week 1 \
  --scoring ppr
```

When `--shadow-snapshot` is used, the builder:

- recomputes and verifies the Shadow Season `content_sha256`;
- requires exact season/week identity;
- rejects duplicate player IDs;
- rejects missing, non-finite or crossed production quantiles;
- inherits the shadow capture timestamp automatically;
- labels the model source with the exact checkpoint.

A loose `--model` file remains supported for development, but it still requires an explicit timezone-aware `--model-captured-at`.

FantasyPros normalized rows already carry `captured_at_utc`. The showcase builder now uses that timestamp automatically unless the operator explicitly supplies `--expert-captured-at`.

## Upstream forecast publisher contract

The only intentional orchestration boundary left outside this workflow is the job that publishes the **weekly production forecast artifact** itself.

That publisher should call this workflow after it uploads the exact forecast used for decisions and provide:

```yaml
uses: ./.github/workflows/weekly-model-performance.yml
with:
  phase: capture
  season: "2026"
  week: "1"
  scoring: PPR
  checkpoint: WEDNESDAY
  model_artifact_run_id: ${{ github.run_id }}
  model_artifact_name: weekly-production-projections-2026-w1-ppr
  model_relative_path: projections.parquet
secrets: inherit
```

Do not schedule a fake model capture merely because Wednesday arrived. The chain only advances when actual forecast bytes exist.

## Data freshness and corrections

GitHub Actions artifacts are retained for 120 days by this workflow. For season-end archival, copy important evidence to durable object storage.

A later source correction must create a new evaluation artifact. It must never overwrite the earlier content-addressed evidence and pretend that was what was known at the time.

That is the operating principle of the whole system: the scoreboard may be playful, but the receipts are not.
