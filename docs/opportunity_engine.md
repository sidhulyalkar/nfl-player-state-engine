# Explicit opportunity-head engine

## Causal ladder

```text
active probability
  → snap share and route participation
  → team plays and dropbacks
  → carry share, target share, red-zone share
  → carries and targets
  → receptions, yards, touchdowns
  → fantasy points
```

`OpportunityHeadBundle` implements this as sequential probabilistic heads. Downstream heads consume upstream predictions rather than same-week observed values.

## Temporal cross-fitting

During training, upstream predictions for a season are generated only by models trained on earlier seasons. Those predictions become the downstream training features. The final deployable heads are then fitted on the full training window using cross-fitted upstream columns.

This avoids teacher-forcing leakage such as training receiving yards with the actual same-week target count and then asking the model to operate with predicted targets at inference.

## Supervision columns

`derive_opportunity_targets` creates target-only columns:

- `opportunity_active`
- `opportunity_snap_share`
- `opportunity_route_participation`
- `opportunity_team_plays`
- `opportunity_team_dropbacks`
- `opportunity_carry_share`
- `opportunity_target_share`
- `opportunity_red_zone_share`
- `opportunity_total_touchdowns`

Raw same-week values are excluded from the pregame feature allowlist. Only lagged and rolling opportunity columns may become predictors.

## Objective priors

The weekly feature path now includes:

- rookie prior;
- team-change prior;
- previous primary quarterback;
- prior quarterback-change indicator;
- optional offensive-line continuity and missingness;
- historical snap, route, volume, share and red-zone states when source data exist.

## Missing-data contract

Snap counts, routes, red-zone opportunities and offensive-line continuity are optional. Missing source families remain missing and receive explicit availability indicators. They are not silently converted into real zeros.

## Commands

```bash
pse build-features \
  --stats data/raw/player_stats.parquet \
  --schedules data/raw/schedules.parquet \
  --output data/processed/weekly_features.parquet

pse train-opportunity-heads \
  --features data/processed/weekly_features.parquet \
  --model artifacts/models/opportunity_heads.joblib \
  --predictions artifacts/predictions/opportunity_holdout.parquet
```

The opportunity heads remain disabled by default until they beat the direct hybrid model across held-out seasons.
