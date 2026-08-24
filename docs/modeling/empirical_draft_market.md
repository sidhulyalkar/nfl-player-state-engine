# Empirical Draft Market

## Purpose

The empirical draft-market layer estimates **market timing**, not football quality.

Its core question is:

```text
P(player survives to my next pick | information available before this draft and current room state)
```

The output may change waitability only after the model clears a frozen chronological evidence gate. Player projections, VORP, scarcity, and football outcome distributions remain separate model layers.

## Authority

The live Draft Room already has a transparent normal-ADP survival approximation. That remains the fallback.

A learned draft-market artifact is allowed to alter `survival_to_next_pick`, `market_urgency`, and the survival component of the live draft score only when its artifact has `promoted=true` under the strict chronological market policy.

An artifact can be trained and saved while blocked. In that case `apply_empirical_survival()` keeps the transparent fallback and does not rewrite the live score.

This is model-layer promotion only. It does not promote the Player State Graph or change player-outcome authority.

## Point-in-time observation contract

Historical draft rows require:

```text
draft_id
player_id
actual_pick
market_adp
position
```

Strong evidence also includes:

```text
draft_started_at
market_snapshot_at
season
platform
scoring
teams
qb_slots_per_team
superflex_slots_per_team
starter_slots_per_team
market_adp_sd
```

`build_draft_survival_observations.py` canonicalizes common draft/market timestamp aliases.

When both timestamps are known:

```text
market_snapshot_at <= draft_started_at
```

must hold. A market snapshot captured after the draft started raises an error instead of entering training.

The builder records:

```text
point_in_time_market_verified
market_snapshot_age_hours
```

If timestamp evidence is incomplete, rows may still be produced for research, but the strict trainer does not promote the resulting artifact unless market provenance is complete. `--allow-unverified-market` is an explicit research-only escape hatch.

## Room-state observations

For each current pick, the builder uses only facts known at that point in the historical room:

- players already selected;
- current pick and manager slot;
- the manager's next snake-draft pick;
- recent positional run;
- archived market ADP and dispersion;
- league format metadata.

It does **not** use final-season fantasy outcomes to build candidate rows or market features.

The derived market audit fields include:

```text
picks_until_next
current_round
next_pick_round
position_market_rank
position_supply_to_next
position_supply_next_round
draft_market_depth
recent_position_run
```

The supply fields are computed from archived market ADP among players that were still available at that historical pick. They are timestamp-safe scaffolds for richer hazard models and room-pressure diagnostics.

## Target

For a candidate who is available at `current_pick`:

```text
survived_to_next_pick = int(actual_pick >= next_pick)
```

This is a market-behavior label. The candidate's eventual NFL performance is irrelevant to the target.

## Chronological holdout

Random draft-room splitting is not a valid promotion test.

`train_chronological_survival_model()` orders entire draft rooms by `draft_started_at` when available and holds out the latest rooms. No draft room appears in both partitions and no future draft can enter training for an older test room.

When only season metadata exists, the holdout consists of complete latest season blocks. Season-only data with one season cannot establish forward transfer and fails closed.

The frozen report records:

```text
split_kind
train_drafts
test_drafts
train_period_end
test_period_start
test_fraction
```

## Baselines

The learned logistic hazard must beat two transparent baselines on the same later drafts.

### Normal-ADP baseline

This is the existing product approximation using ADP, the user's next pick, and ADP dispersion.

### Empirical ADP-bucket baseline

This baseline is fitted only on the earlier training rooms. It estimates historical survival frequency by:

```text
league format x position x ADP-distance bucket
```

with hierarchical fallback to position/bucket, bucket, then the global training rate. Rates are shrunk toward the training global mean.

No holdout labels enter the bucket table.

The promotion comparison uses the baseline with the lower holdout Brier score. A learned model therefore cannot claim victory merely by beating the weaker simple baseline.

## Metrics

Every chronological holdout reports:

- Brier score;
- log loss;
- expected calibration error;
- positive survival rate;
- ROC AUC when both classes are present.

The same holdout is sliced by a league-format key containing:

```text
teams
scoring
QB starter slots
SUPER_FLEX slots
total starter slots
```

This prevents a model that improves pooled results while materially regressing a supported 2QB or custom-roster format from receiving blanket authority.

## Promotion gates

The default strict artifact is blocked unless all applicable conditions clear:

1. total rows and independent draft rooms meet minimum support;
2. the chronological holdout contains both survival outcomes;
3. Brier score improves over the best simple baseline by the configured minimum;
4. calibration does not regress beyond `max_ece_regression`;
5. no sufficiently supported league-format slice regresses beyond `max_format_brier_regression`;
6. point-in-time market evidence is fully verified unless the operator explicitly chooses research-only unverified mode.

The gate thresholds are CLI parameters and are written into the training report. They should be chosen before reading the new holdout result, not tuned afterward to rescue a preferred model.

## Training

Build timestamp-safe observations:

```bash
python scripts/build_draft_survival_observations.py \
  --drafts data/raw/fantasy/historical_drafts.parquet \
  --output data/processed/draft_survival_observations.parquet
```

Train the chronological challenger:

```bash
python scripts/train_draft_survival_model.py \
  --observations data/processed/draft_survival_observations.parquet \
  --output artifacts/models/draft_survival/draft_survival.joblib \
  --report artifacts/models/draft_survival/metrics.json
```

The report records:

- Git SHA;
- observation path, bytes, and SHA-256;
- model path, bytes, and SHA-256;
- chronological split metadata;
- model metrics;
- both baseline metric sets;
- format slices;
- market verification rate;
- promotion gates, blockers, and result.

## Live behavior

The existing live integration remains fail closed:

```text
artifact missing        -> normal ADP fallback
artifact unpromoted     -> normal ADP fallback
artifact promoted       -> empirical survival probability
```

An unpromoted artifact does not rewrite `live_draft_score`.

The learned market model is only one input to a draft decision. It does not overwrite player projections, league scoring, VORP, or roster value.

## Next evidence stages

After chronological survival calibration is credible:

1. wire the timestamp-safe market-supply fields into a richer hazard challenger and compare it with the simple logistic head;
2. add roster needs of managers selecting before the user's next pick when historical room state supports it;
3. replay `WAIT` decisions and measure regret by format;
4. compare ADP-only, VORP-only, current score, survival-aware, and survival-plus-roster-simulator policies on frozen historical drafts;
5. only after multi-format replay succeeds, consider individual opponent tendencies with enough repeat-draft evidence.

Do not jump directly to manager personality models. Sparse friend-league history is not enough evidence to learn a stable drafting persona.
