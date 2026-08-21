# Model Accuracy Audit — 2026-08-21

This audit records the model-authority boundary after reviewing the repository's feature-branch lineage through v0.16 and both open Player State Graph branches.

The purpose is to separate three claims that must never be conflated:

1. **implementation correctness** — code obeys its stated mathematical and football contracts;
2. **historical predictive evidence** — a challenger beats frozen timestamp-safe baselines out of sample;
3. **production authority** — a challenger is allowed to change live rankings or decisions.

A green unit-test suite establishes only the first category.

## Authoritative production boundary

The established direct player quantile model remains the production forecast spine. The v0.10–v0.16 football-world models and the Player State Graph remain challengers until frozen replay demonstrates lift.

Merging research infrastructure into `main` does **not** promote it.

The Player State Graph and forecast fusion must continue to emit research/challenger provenance and must not silently replace the direct forecast bundle.

## Feature-branch reconciliation

The historical v0.7–v0.16 feature branches were integrated through their corresponding merged pull requests. Their surviving branch refs are historical development heads, not independent releases to merge again.

Two parallel Player State Graph branches remained open:

- `agent/player-state-graph-v2` / PR #17;
- `agent/player-state-graph` / PR #18.

PR #18 is the canonical integration line because it has the broader product/draft integration and the stronger regression suite. PR #17 is a donor branch rather than a second truth engine. Its useful joint-team opportunity-allocation idea should be incorporated only through an isolated, benchmarked follow-up instead of merging a duplicate `state_graph` package wholesale.

## Correctness hardening completed on the canonical graph

### Outcome coherence

Raw football outcomes are constrained before fantasy scoring:

- receptions cannot exceed targets;
- receiving touchdowns cannot exceed receptions;
- pass completions cannot exceed attempts;
- passing touchdowns cannot exceed completions;
- interceptions cannot exceed incompletions;
- player carries cannot exceed sampled team carries.

Passing-TD and interception conditional probabilities are derived so the configured per-attempt marginal rate is preserved whenever the requested marginal is feasible.

### QB carry-share semantics

The existing opportunity engine defines `carry_share` as:

`player carries / team carries`

That quantity already contains QB scrambles. The research graph therefore no longer adds scrambles on top of a second draw from total carry share. Scrambles constrain passing attempts and form a lower bound on total QB carries, while total QB carries remain bounded by team rushes.

### Point-in-time role state

Dynamic role updates now:

- filter on `available_for_prediction_at`;
- process eligible evidence in football event-time order;
- refuse incremental rewinds from older observations;
- decay stale posterior evidence back toward the positional prior at forecast time;
- decay role-change confidence when no confirming evidence arrives.

This prevents late publication of an old row from corrupting temporal state and prevents stale roles from remaining permanently overconfident.

### Fantasy season simulation

Managed-league season simulation no longer chooses the hindsight-optimal lineup separately inside every Monte Carlo realization.

Instead, starters are selected from pregame expected player values and remain fixed across the paired outcome paths for that manager-week. Realized outcomes then determine matchup results.

This removes best-ball/oracle bias from expected wins, playoff probability, and championship probability.

Six-team playoffs now give the two highest seeds opening-round byes under the generic reseeded bracket contract.

### Quantile calibration and fusion

Crossed q10/q50/q90 triplets are repaired consistently during both fitting and inference and the repair is surfaced as a diagnostic.

The recency-weighted conditional calibrator is explicitly described as **conformal-style research calibration**, not an exact finite-sample conformal guarantee, because recency weighting and hierarchical shrinkage relax ordinary exchangeability assumptions.

### Statistical experiment plumbing

Paired season/week cluster bootstrap now resamples block sums and counts, so its confidence interval targets the same row-weighted effect as its reported point estimate even when weeks contain different numbers of player rows.

Promotion metadata now fails closed on explicit thresholds for:

- season consistency;
- position consistency;
- coverage;
- historical source availability;
- negative controls;
- minimum useful effect;
- confidence-interval direction.

## Calculations reviewed and retained

### League scoring

The authoritative scoring path applies league weights to raw correlated simulation draws. Quantile-only rescoring is correctly labeled approximate because quantiles of sums are not generally sums of quantiles.

### Replacement and scarcity

Fantasy valuation derives replacement levels from league starter/flex demand and allocates flex seats dynamically. Positional scarcity depends on replacement slopes and supply rather than a fixed universal multiplier.

These are structurally reasonable league-dependent calculations but still require downstream draft/transaction replay for claims of decision lift.

### Uncertainty decomposition

The graph's uncertainty display is one-component-fixed variance-reduction sensitivity attribution. The normalized shares are **not** a causal or additive Sobol decomposition and must remain labeled accordingly.

### Draft reliability

`draft_reliability_score` is a transparent guardrail heuristic combining source coverage, market quality, projection uncertainty, challenger agreement, Monte Carlo error, and freshness. It is not a calibrated probability.

The empirical draft-survival model remains authoritative only when its own promotion gate beats the transparent ADP fallback.

## Remaining scientific blockers before production promotion

### 1. Joint team opportunity conservation

The canonical Player State Graph currently forecasts one player at a time. Separate teammate forecasts can therefore imply target or carry shares whose sum exceeds the same team's opportunity pool.

The PR #17 joint multinomial allocation concept is useful, but it should be ported into the canonical graph through a dedicated experiment that proves better calibration and downstream scoring without degrading individual marginals.

Until then, do not call independently generated teammate graphs a fully coherent team world.

### 2. Complete scoring-event generation

The research graph does not yet generate every possible custom-scoring event, notably a calibrated fumble/fumble-lost and two-point-conversion process. Exact scoring means the scoring transform is exact for the statistics supplied, not that every league scoring event is already generatively modeled.

### 3. Availability conditioning contract

The repository contains both explicit availability probabilities and fantasy quantiles. Every live artifact must declare whether player quantiles are:

- conditional on active;
- unconditional with inactive zero-mass already included.

Downstream valuation must multiply by availability only in the first case. This needs an explicit artifact contract plus replay tests before changing existing production behavior.

### 4. Touchdown-role interaction

The research graph modifies touchdown probabilities with environment and red-zone/goal-line role states. Historical execution rates may already encode some of that role information. Only frozen ablations can determine whether the modifiers add signal or double-count it.

### 5. Calibration on frozen future blocks

Calibration and fusion must be fitted only on rows strictly earlier than each evaluation block. Reporting calibration on the same rows used to fit the calibrator is a unit-test check, not predictive evidence.

### 6. Draft-survival temporal validation

The empirical survival model currently uses draft-group holdout. Before increasing authority, benchmark chronological or season/platform-separated holdouts and calibration, not only a random grouped split.

### 7. Platform-specific playoff semantics

The generic reseeded fantasy playoff bracket is mathematically consistent, but exact platform parity requires the league snapshot to normalize real playoff-team counts, byes, reseeding, multi-week rounds, and tiebreak policy.

## Required promotion sequence

The next graph-vs-production experiment should freeze all model choices before scoring and compare at minimum:

1. direct production quantile model;
2. rolling-stat baseline;
3. position-prior baseline;
4. opportunity-only challenger;
5. Player State Graph;
6. direct + graph fusion;
7. external consensus/market as a separate expert, not silently embedded in the player model.

Use expanding training history and held-out seasons with prediction-time source availability. Report by position and target:

- q10/q50/q90 pinball loss;
- interval coverage and width;
- median MAE/RMSE;
- CRPS when draws exist;
- rank correlation;
- active-status Brier score;
- role-change detection quality;
- downstream lineup regret, waiver value, draft value-over-replacement, and season outcome deltas.

Use paired season/week blocks, negative controls, position/season consistency, effect-size gates, and false-discovery control for families of hypothesis tests.

## Definition of "fundamentally accurate"

For this repository, the phrase should mean:

- temporally legal inputs;
- internally possible football outcomes;
- exact league scoring given generated stats;
- no hindsight decision oracle;
- mathematically aligned estimators and confidence intervals;
- explicit uncertainty and provenance;
- frozen out-of-sample evidence against strong baselines;
- no production promotion until those gates pass.

The current hardening materially improves the first six. The final two require the real multi-season benchmark and 2026 shadow-season evidence rather than additional code assertions.
