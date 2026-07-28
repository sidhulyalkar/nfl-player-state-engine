# NFL Player State Engine: Project Goals

## North-star goal

Build a trustworthy open player-state system: a timestamped, probabilistic model of NFL participation, opportunity, efficiency, matchup context, and uncertainty that improves fantasy decisions and supports rigorous paper-market research.

The target is not a magical single-number oracle. It is a changing distribution:

```text
player output distribution
  = team environment
  × probability active
  × expected participation
  × opportunity share
  × conditional efficiency
  × correlated game script
  × irreducible uncertainty
```

## Scientific claim

A hierarchical, target-aware player-state model can produce better-calibrated weekly outcome distributions than rolling production statistics and historical position priors under strict multi-season, point-in-time evaluation.

Every later claim is incremental:

1. Does target-aware and position-aware modeling beat transparent baselines?
2. Does opportunity decomposition improve the numerical engine?
3. Does official availability evidence add value?
4. Does timestamped news add value beyond official reports?
5. Do public player-context features add value beyond objective football context?
6. Do sequence or tracking representations transfer across seasons, players, and teams?

## Gate 1 status: completed

The first real benchmark used official nflverse weekly player statistics and schedules from 2020–2025:

- 2020 regular season as warm-up;
- 2021–2025 entirely out of sample;
- 34,883 QB/RB/WR/TE player-weeks;
- q10/q50/q90 quantile engine;
- five-game rolling and historical position-prior baselines;
- explicit pregame feature allowlist;
- evaluation by target, season, position, calibration, and interval width.

The pooled engine won six of seven targets by mean pinball loss. Carries failed because the pooled model mixed incompatible zero-inflated position processes. A position-specific carries model corrected the failure and narrowly beat the rolling baseline. Production v0.3 therefore uses a hybrid target-aware bundle.

Full results: `docs/benchmark_real_2020_2025.md`.

## Gate 2 implementation status: v0.4

The calibrated opportunity architecture is now implemented in causal order:

```text
active probability
  -> snaps and routes
  -> team play volume
  -> carries and targets
  -> receptions and yards
  -> touchdowns and fantasy points
```

The remaining Gate 2 validation requirements are:

- correct passing-yard undercoverage and target/reception overcoverage;
- improve mean pinball loss across multiple held-out seasons;
- preserve or improve position stability;
- archive every out-of-sample prediction;
- beat simpler recency and position-prior models;
- demonstrate that added complexity improves more than one headline aggregate.

## Gate 2 experiment status: v0.5

A frozen residual ablation over 23,003 out-of-sample player-weeks tested whether lagged carries, targets, shares, participation-history proxies and role trends add value beyond the numerical champion. They did not: objective plus participation features worsened mean pinball by 3.14% and reduced interval coverage. The deliberately leaked future-shift control improved pinball by 27.04%, confirming that the harness can detect informative role signals when they exist.

The next accepted Gate 2 evidence must come from genuinely new sources: prior-week offensive snaps, pass-play participation, depth movement and timestamped official availability. Source-family coverage and ID-resolution quality are first-class metrics.

## Fantasy decision north star

Optimize manager decisions rather than one global player ranking. The repository now treats start/sit, waiver, trade, draft, stash and dynasty decisions as distinct utilities over the same probabilistic player state. Success metrics include lineup regret, waiver upgrade, FAAB efficiency, trade value after replacement, draft value over acquisition cost and calibrated breakout probabilities.

## Product vision

### Fantasy layer

- weekly probabilistic projections;
- start/sit distributions rather than rankings alone;
- waiver and role-change alerts;
- trade and roster simulation;
- league-specific scoring;
- explanations grounded in opportunity, matchup, and availability.

### Research layer

- immutable source and prediction archives;
- temporal benchmark suite;
- calibration and drift monitoring;
- champion/challenger registry;
- paper-only market evaluation;
- feature ablation registry;
- counterfactual game and workload scenarios.

### Representation layer

Longer term, learn reusable football states from:

- play-by-play sequences;
- personnel and formation structure;
- player tracking trajectories;
- team and player temporal states;
- official injury and transaction evidence;
- timestamped public football language.

## Continual-learning philosophy

The engine should grow with new completed weeks, but not through uncontrolled online updates.

Each refresh should:

1. retrieve and checksum official data;
2. rebuild point-in-time features;
3. train an expanding-window challenger;
4. rerun baselines and calibration gates;
5. register the result;
6. require manual champion promotion by default.

This keeps learning cumulative while preventing a strange week, schema change, or data correction from quietly replacing a trusted model.

## Intelligence philosophy

Injury, news, and public social content are evidence streams, not oracle dust.

Permitted collection paths include official APIs, licensed feeds, RSS, and pages genuinely served to an empty unauthenticated browser when robots.txt allows collection. Public-page rendering may execute JavaScript, but it must stop on login, CAPTCHA, or challenge pages. Public-figure status does not authorize access-control circumvention.

Every derived feature must retain:

- source URL;
- author or publisher type;
- authored timestamp;
- collection timestamp;
- extractor version;
- supporting evidence;
- confidence and caveats.

“Persona” features are limited to observable public football-context signals such as training emphasis, recovery discussion, leadership language, team orientation, matchup specificity, and role expectations. They are not private personality truth, clinical labels, or motivation scores.

## Intelligence activation ladder

### Stage 1: official availability

- practice status;
- game designation;
- inactive list;
- transactions and injured reserve;
- depth-chart movement.

### Stage 2: objective opportunity

- snap share;
- route participation;
- team plays and dropbacks;
- target and carry share;
- red-zone role;
- quarterback and offensive-line changes.

### Stage 3: structured news

- workload restrictions;
- starter/backup announcements;
- committee changes;
- coach-described role changes;
- timestamped matchup preparation.

### Stage 4: public player context

- training/recovery language;
- explicit role expectations;
- matchup specificity;
- source diversity and visibility;
- evidence-strength and uncertainty modifiers.

No stage advances without an isolated, frozen, point-in-time ablation and negative controls.

## Non-negotiable modeling rules

1. No random row splits for weekly football data.
2. No feature may use information published after the prediction cutoff.
3. No raw same-game outcome columns in the feature matrix.
4. No consensus projection enters without a timestamp and separate ablation.
5. No model promotion without baseline comparison and calibration inspection.
6. No betting-performance claim without archived odds, no-vig comparisons, and clustered uncertainty.
7. No intelligence feature receives special status because it sounds compelling.
8. Every complex model must beat a simpler one on a frozen protocol.
9. No login circumvention, private content collection, or sensitive-trait inference.
10. No automatic real-money wagering.

## Success ladder

### Level 1: trustworthy benchmark

Completed. Multi-season results, hashes, position calibration, and failure analysis are bundled.

### Level 2: opportunity engine

Snap, route, target, carry, and team-volume submodels improve distributions and detect role changes.

### Level 3: availability engine

Official injury reports, transactions, and depth charts improve participation and workload uncertainty.

### Level 4: context intelligence

Timestamped news and public-context features demonstrate stable incremental value in preregistered ablations.

### Level 5: football world model

A sequence/graph model learns transferable player, matchup, and game states and improves multiple downstream tasks.

## What not to optimize yet

- sportsbook integrations or automated wager placement;
- giant language-model fine-tuning before opportunity heads;
- scraping behind authentication;
- elaborate dashboards before calibration is sound;
- public sentiment without timestamps and negative controls;
- a grand football foundation model before simple decomposition stops winning.

The scoreboard remains scientific: did the model beat the baselines, remain calibrated, and know when the game could still turn into weather with shoulder pads?


## v0.4 implementation boundary

Implemented:

- earlier-season target-position conformal calibration;
- embedded calibrators for continual challenger artifacts;
- explicit temporally cross-fitted opportunity heads;
- rookie, team-change, quarterback-change and optional OL-continuity context;
- official practice, designation, inactive, IR/PUP, transaction, depth and workload evidence;
- timestamped structured news claims with provenance;
- capped residual/uncertainty adjustment for softer evidence;
- complete intelligence ablations and negative controls.

Not yet scientifically promoted:

- opportunity heads over the direct hybrid engine on real snap/route data;
- any official availability feature family;
- structured news;
- public player context.

Code availability is not evidence of predictive value. Each family remains disabled until its frozen multi-season experiment passes the documented gates.

## v0.6 product goal: league-aware decision operating system

The research engine becomes a product only when it understands the manager's complete decision environment.

```text
NFL player state
  + league scoring and roster rules
  + ownership and free-agent state
  + rival roster needs
  + schedule and playoff context
  + user risk preference
  = decision-specific fantasy utility
```

### Product claim

A league-aware system built on calibrated player distributions can reduce lineup regret, improve roster-relative waiver decisions, and identify fairer mutually beneficial trades compared with generic global rankings.

### Product gates

1. **Import fidelity:** scoring, roster slots, ownership, free agents, and standings match the platform.
2. **Identity coverage:** relevant players resolve to canonical IDs, with unresolved cases visible.
3. **Decision validity:** every lineup is legal and every trade is evaluated on both post-trade rosters.
4. **Predictive validity:** archived distributions beat baselines and remain calibrated.
5. **Decision value:** recommendations improve lineup regret, waiver upgrades, or trade utility.
6. **Explanation grounding:** Gemini uses tool results and never invents player values.
7. **Operational trust:** freshness, model version, missing sources, and uncertainty are visible.

### Frontend north star

Fourth Down Lab should combine the strongest parts of fantasy platforms without reproducing their clutter:

- platform-quality league and roster navigation;
- analyst-quality probabilistic player cards;
- research-quality model diagnostics;
- roster-aware trade, waiver, and lineup optimization;
- a conversational layer that can traverse the league graph through typed tools;
- an aesthetic interface where uncertainty is legible rather than hidden.

The detailed product plan lives under `docs/product/` and the Google AI Studio starter is under `apps/gemini-fantasy-console/`.
