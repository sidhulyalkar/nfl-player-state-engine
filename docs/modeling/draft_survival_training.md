# Empirical draft-survival training

## Target

Estimate `P(player is still available at my next pick | current room state, market, league format)`.

This is a market-behavior model, not a football projection.

## Required raw table

One row per player per historical draft with at least `draft_id`, `player_id`, `actual_pick`, `market_adp`, and `position`.

Strongly recommended fields are `market_adp_sd`, `platform`, `teams`, `scoring`, `qb_slots_per_team`, `superflex_slots_per_team`, `starter_slots_per_team`, `draft_date`, and `adp_timestamp`.

`market_adp` must be the market information available **before that historical draft**. Do not join a later end-of-preseason ADP snapshot onto an earlier draft.

## Observation builder

```bash
python scripts/build_draft_survival_observations.py \
  --drafts data/raw/fantasy/historical_drafts.parquet \
  --output data/processed/draft_survival_observations.parquet
```

The builder reconstructs each snake-draft decision point, the manager's next pick, recent positional runs, the player pool still available at that moment, and whether each candidate actually survived to the next selection.

## Training and promotion

```bash
python scripts/train_draft_survival_model.py \
  --observations data/processed/draft_survival_observations.parquet \
  --output artifacts/models/draft_survival/draft_survival.joblib \
  --report artifacts/models/draft_survival/metrics.json
```

Drafts, not rows, are held out together. The primary promotion gate is Brier score against the transparent normal-ADP survival approximation already used by the engine. The trained artifact can be saved for inspection even when it loses, but `promoted=false` artifacts are never allowed to replace the fallback probability in the live board.

## Why no bundled model yet

The repository does not currently contain a sufficiently broad, timestamped archive of the user's Sleeper/ESPN draft rooms plus contemporaneous ADP. Shipping a model trained on a mismatched public format and calling it empirical for these leagues would create false precision. v0.8 therefore ships the complete training, evaluation, promotion, and serving path while preserving the transparent fallback until real data clears the gate.

## Data flywheel

Archive future live drafts with completed picks and timestamps, exact league settings, the market ADP snapshot used by the War Room, the full board state at each user selection, and `WAIT` recommendations plus whether the player returned. Each draft then becomes clean training evidence for the following season.
