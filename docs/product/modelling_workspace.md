# Fourth Down Lab modelling workspace

This guide describes how to use the Product API and frontend as one decision system without confusing production forecasts, league valuation, market timing, and research challengers.

## Mental model

The workspace has three authority layers.

### Production football projection

The direct player quantile model owns the production q10 / q50 / q90 forecast.

### League decision layer

Python converts production football information into the active league's decision context. This layer owns exact supported scoring translation, replacement economics, VORP, roster fit, draft actions, lineup allocation, waiver value, trade value, and other league-specific outputs.

### Research layer

Player State Graph, room simulation challengers, historical diagnostics, and scenario sensitivity remain inspectable research evidence. They may explain disagreement or reveal a useful hypothesis without changing production authority.

The browser should never collapse these layers into one unlabeled score.

## Workspace map

| Surface | Primary question | Production authority | Research content |
|---|---|---|---|
| Draft Room | Who should I take now? | Yes | Room survival and two-turn challengers are labeled |
| Player Intelligence | What is the complete case for this player? | Yes | Shadow Lab and historical replay |
| Portfolio | What bets am I repeating across leagues? | Descriptive roster truth | No diversification mandate |
| League OS | What should I do across the season? | Yes | Detailed research console remains available |
| Model Observatory | Should I trust a new model layer? | No live decision authority | Calibration, replay, evidence gates |

## URL routing

Workspace state is encoded in the query string.

```text
?workspace=draft
?workspace=intelligence
?workspace=portfolio
?workspace=league
?workspace=model
```

Player Intelligence additionally persists the selected league and player:

```text
?workspace=intelligence&league=LEAGUE_ID&player=CANONICAL_PLAYER_ID
```

Changing the selected player replaces the current URL rather than adding one browser-history entry per click. Moving between workspace surfaces pushes browser history so Back and Forward behave like normal product navigation.

If a deep-linked player is not present on the current league board, the UI falls back to a valid player from that league instead of requesting an unrelated stale ID.

## Draft-day workflow

### Before the room opens

1. Confirm the league appears in Draft Room and Player Intelligence.
2. Confirm the correct team/roster is selected.
3. Confirm format label, team count, QB/SF structure, scoring, and median settings.
4. Check league readiness and scoring provenance.
5. Open Portfolio and inspect repeated player/team exposure from earlier drafts.
6. Open Model Observatory once to see whether any research artifact is missing or badly calibrated.

### On the clock

1. Start in Draft Room.
2. Read the primary action, VORP, wait cost, return probability, projection range, and trust state.
3. Use the shortlist for the immediate alternatives.
4. Select 2 to 5 candidates when the choice is genuinely close.
5. Treat external ADP/ranking disagreement as an investigation signal, not as a forced average.
6. Move to Player Intelligence when a player's full role, uncertainty, history, or graph disagreement matters.
7. Return to Draft Room for the actual pick decision.

The live board remains the authority surface even when a research scenario looks exciting.

## Player Intelligence workflow

For one player, read the dossier top to bottom.

### Projection geometry

Start with q10 / q50 / q90 and replacement margin. A high median with a very wide interval is a different decision object from the same median with a narrow interval.

### Six-decision matrix

A player can rank differently for:

- start/sit;
- waiver;
- trade;
- draft;
- stash;
- dynasty.

Do not carry a single context-free rank across these decisions.

### Signals

Availability, opportunity, breakout, role growth, scheme, schedule, playoff schedule, and prospect signals are shown only when the production artifact contains them.

Missing optional signals remain missing. React does not fabricate replacements.

### Frozen player history

Exact-player replay answers whether prior held-out outcomes were inside the forecast interval and how the median missed. It is diagnostic evidence, not a guarantee that the next forecast is correct.

## Shadow Lab

Shadow Lab reads mounted Player State Graph artifacts.

Expected artifact root:

```text
artifacts/player_state_graph
```

Expected files include:

```text
player_state_graph_summaries.parquet
dynamic_role_states.parquet
coherent_scored_draws.parquet
player_intelligence_cards.json
run_manifest.json
```

### Direct-vs-graph comparison

The direct distribution remains authoritative. The graph distribution is shown beside it as a research challenger.

Useful disagreement questions include:

- Is the graph median materially higher or lower?
- Is the disagreement mostly median shift or interval width?
- Does the graph identify a role transition the direct model may smooth over?
- Is the graph state mature or newly changed?
- Does the opportunity allocation look coherent across teammates?

### Opportunity conservation

Target and carry shares are audited at the modeled team-week level.

When modeled raw shares total less than 100%, the remaining share belongs to an explicit unmodeled teammate residual.

When modeled raw shares exceed 100%, they are normalized back to legal support and that normalization is visible.

Inactive modeled players do not silently consume nominal opportunity.

### Scenario controls

Scenario controls adjust bounded research sensitivity for:

- role multiplier;
- team-volume multiplier;
- availability probability.

The resulting values answer a counterfactual question such as "how sensitive is this player to a 10% role increase?" They are not retrained or recalibrated production forecasts.

Scenario output cannot overwrite live ranks or recommendations.

## Scoring-contract guard

A graph artifact is decision-comparable only when its run manifest matches the relevant fantasy scoring contract.

At minimum the comparison checks the score weights and tight-end premium used to score the graph draws.

Examples of intentional fail-closed behavior:

- graph artifact scored as PPR, active league is half-PPR;
- base PPR weights match but active league has a TE reception premium absent from the graph run;
- graph artifact predates `run_manifest.json` and its scoring contract cannot be verified.

In these cases the graph may remain visible as research context, but `decision_comparable` is false.

## Model Observatory workflow

Read four things separately.

### Calibration

Empirical q10-q90 coverage should be judged against the nominal 80% target. Undercoverage means intervals are too optimistic. Overcoverage can indicate intervals are too wide.

### Accuracy

q50 MAE and median bias describe the point forecast. A good median does not automatically imply a good distribution.

### Sharpness

Interval width is useful only in conjunction with calibration. Narrow intervals with poor coverage are not an improvement.

### Quantile loss

Pinball loss evaluates the distribution directly and keeps q10/q50/q90 performance in view.

Position and season slices should be inspected before trusting an aggregate win.

## Graph promotion evidence

A better headline graph loss is not enough for promotion.

The promotion policy remains fail-closed on:

- evidence tier;
- useful effect size;
- confidence interval;
- season consistency;
- position consistency;
- week consistency;
- forecast coverage;
- live data availability;
- negative controls;
- downstream fantasy decision evidence;
- FDR when multiple hypotheses are evaluated.

The Model Observatory surfaces blockers instead of hiding them behind one research score.

## Portfolio workflow

Portfolio aggregates the user's resolved roster across stored league snapshots.

### Identity

Canonical player IDs are used when available. Platform-scoped IDs remain explicitly scoped to their platform when canonical mapping is unavailable.

Cross-platform rows are not joined merely because names look similar.

### User roster resolution

The system attempts to resolve the user's roster from:

1. imported external user identity;
2. explicit snapshot metadata such as selected/external roster ID;
3. the only roster when a snapshot contains exactly one roster.

If a multi-roster snapshot remains ambiguous, it is excluded from Portfolio instead of choosing roster 1.

### Interpreting exposure

High exposure can be rational if the model repeatedly identifies a strong player. Low exposure is not automatically superior.

Use Portfolio to make correlated bets visible, especially before adding another copy of a player or another cluster of players from the same NFL offense.

## League storage and live sync

The Product API reads both:

```text
data/product/leagues
data/product/live_leagues
```

Live portfolio syncs can use connection-key filenames such as:

```text
league_8_ppr_a.json
```

while the embedded snapshot contains a different platform league ID.

`LeagueSnapshotStore.find()` and `iter_snapshots()` resolve by embedded identity, so Product API consumers do not need filename conventions to discover live leagues.

## Troubleshooting

### A league appears in Draft Room but not Player Intelligence

Check that the operational API is running the latest workspace routes and that the snapshot is readable from either configured league store. Player Intelligence uses the unified `/v1/intelligence/leagues` endpoint rather than the legacy primary-store-only list.

### Player Intelligence opens the wrong player after changing leagues

The current implementation validates the selected player ID against the new league board and falls back to the first valid player. A stale deep-link ID should not be carried into another league.

### Shadow Lab says unavailable

Check `PSE_PLAYER_STATE_GRAPH_ROOT` and the expected graph artifacts. The UI intentionally does not synthesize latent state when research artifacts are absent.

### Shadow Lab says not comparable

Inspect `run_manifest.json`. The graph may have been scored under a different league scoring contract or TE premium.

### Portfolio has unresolved leagues

Inspect `external_user_id`, roster manager IDs, and `external_roster_id` / selected roster metadata. Do not fix this by defaulting to the first roster.

### Historical player replay is empty

The frozen benchmark must contain the exact canonical player ID. Name-only matching is intentionally not used as a silent substitute.

## Release checklist

Before treating a branch as a product-ready candidate:

1. Frontend production build passes.
2. Ruff passes.
3. Python compileall passes.
4. Full pytest passes.
5. Exact head SHA is recorded in the PR.
6. Exact CI run is recorded in the PR.
7. Production-vs-research authority language is preserved.
8. A graph implementation change is not described as a model promotion unless the frozen evidence gate actually clears.
