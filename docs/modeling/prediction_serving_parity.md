# Prediction Serving Parity

## Why this exists

Historical model validation and live serving must use the same feature semantics. A feature can be leakage-safe during a historical expanding-window benchmark and still be invalid at serving time if the future row cannot reconstruct the same strictly-prior state.

The original weekly slate builder inferred active players and teams from each player's latest statistical row. That is useful in-season, but it is not a reliable roster authority around an offseason boundary:

- traded/free-agent players can remain attached to their prior team;
- rookies have no prior statistical row and disappear;
- exact-week position/team/opponent aggregate joins are missing for genuinely future weeks;
- prior-QB context can be missing even though it is populated in historical training rows.

`build_current_roster_prediction_slate()` is the fail-closed serving boundary for a current roster snapshot.

## Identity authority

The serving boundary uses GSIS/player IDs only. It does not join historical outcomes to current players by name.

For nflverse inputs:

```text
rosters.gsis_id == player_stats.player_id
```

Rows with a contracted fantasy-relevant roster status but no GSIS identity block the slate by default.

Cross-team duplicate GSIS identities also block the slate when no temporal ordering field is available. The system must not invent which team is current.

## Roster-status semantics

Included statuses are explicit NFL-contract states that can still represent a fantasy asset:

```text
ACT E14 EXE INA PUP RES RSN SUS
```

Released/free-agent/practice-squad states are excluded from the production player pool:

```text
CUT DEV NWT RET RFA RSR TRC TRD TRL TRT UFA
```

An unknown status blocks serving by default. Upstream schema changes therefore become observable rather than silently changing the draft pool.

Excluded rows are not counted as unresolved identities. This distinction matters when a released player has a missing GSIS ID.

## Trades and rookies

Current roster truth owns `recent_team` for the future row.

A veteran moved to a new team keeps his GSIS-linked historical lag features while `team_changed_prior` becomes true.

A rookie/no-history player is retained explicitly with:

```text
player_history_count = 0
is_rookie_prior = 1
```

The model may still be poorly calibrated for that cohort. Inclusion in the slate is not a claim that the existing weekly model has earned rookie preseason authority.

## Forward aggregate context

The historical feature builder creates position, team and opponent rolling context by joining exact historical weeks. A genuinely future week has no realized row in those aggregate tables.

Serving therefore reconstructs the equivalent strictly-prior state from the latest completed observations:

- `position_*_prior4`
- `team_*_roll4`
- `opp_allowed_*_roll4`
- `previous_primary_qb`
- `quarterback_changed_prior`

For a future week, the most recent completed game is legitimately part of the prior window. This matches the historical `shift(1)` meaning without manufacturing future outcomes.

## Diagnostics

Every slate returns `PredictionSlateDiagnostics` with:

- eligible skill-position roster rows;
- included contracted rows;
- resolved identities;
- unresolved contracted identities;
- excluded roster-status rows;
- unknown statuses;
- ambiguous cross-team identities;
- veterans;
- rookies/no-history players;
- detected team changes;
- final projection rows.

Production operators should persist this object next to the prediction artifact.

## CLI

```bash
python scripts/build_current_roster_prediction_slate.py \
  --stats data/raw/nflverse/player_stats.parquet \
  --schedules data/raw/nflverse/schedules.parquet \
  --rosters data/raw/nflverse/rosters.parquet \
  --season 2026 \
  --week 1 \
  --output data/processed/slate_2026_w01.parquet
```

The three `--allow-*` flags exist for research/debugging only. A production draft workflow should keep the default fail-closed behavior.

## Scope boundary

This fixes weekly serving parity. It does **not** make the weekly autoregressive model a valid preseason season-total model.

At draft time, Weeks 2-18 have not happened. Repeatedly calling the weekly model across the future schedule would either reuse stale state or implicitly treat future weeks as missed games. Summing weekly quantiles would also be mathematically invalid because quantiles are not additive.

Season-long draft valuation therefore needs a separate direct preseason season-distribution model, evaluated at season boundaries. The weekly engine remains the production authority for weekly player-state forecasting unless and until that separate season model earns its own promotion.
