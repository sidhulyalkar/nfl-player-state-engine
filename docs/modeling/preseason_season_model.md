# Direct Preseason Season-Distribution Model

## Problem statement

The production weekly quantile engine answers a game-time question:

```text
What is this player's distribution for the next NFL game given completed prior games?
```

A fantasy draft in August asks a different question:

```text
What is this player's full regular-season distribution given only information available at season start?
```

Those two problems must not be collapsed.

Repeatedly applying the weekly autoregressive model across Weeks 1-18 would either reuse stale state or require feeding simulated future outcomes back into future features. Summing weekly q10/q50/q90 is also invalid because quantiles are not additive.

The direct preseason model therefore has its own dataset, benchmark, gate and authority.

## Candidate population

The historical candidate universe comes from the Week 1 weekly roster snapshot, not from the player-stat table.

This is critical. A player who is rostered but records no weekly player-stat row is still a fantasy asset and must appear as a zero-output season. Otherwise the training population is conditioned on producing a box score and the model systematically understates participation/role risk.

The dataset performs this sequence:

1. freeze each target season's Week 1 skill-position roster universe;
2. resolve players by GSIS ID only;
3. exclude explicit released/free-agent/practice-squad states;
4. retain active, inactive, reserve, PUP and suspended contracted players;
5. aggregate regular-season football outcomes by player and season;
6. left-join those outcomes onto the roster universe;
7. fill missing target-season outcomes with zero;
8. construct predictors only from static metadata, opening-roster structure and exact prior seasons.

A missing 2024 row cannot cause 2023 production to masquerade as `prior1_*` for 2025. Prior features join exact calendar seasons.

## Season-start feature family

The frozen initial feature family contains:

- position;
- current opening team;
- opening roster status;
- age at September 1;
- draft year, round and pick;
- rookie indicator;
- count of prior opening-roster seasons;
- current-team change from the exact prior season;
- team positional competition count;
- total team skill-position roster count;
- exact prior-season and two-season-ago roster presence;
- exact prior-season and two-season-ago games with a player-stat row;
- exact prior-season and two-season-ago totals for each modeled football outcome.

It intentionally excludes target-season weather, spreads, totals, practice reports, weekly depth movement and any other variable unavailable for the full season at draft time.

## Initial target family

The candidate directly models q10/q50/q90 for:

```text
fantasy_points_ppr
passing_yards
passing_tds
interceptions
rushing_yards
rushing_tds
receptions
receiving_yards
receiving_tds
```

The component targets are necessary because custom fantasy scoring should eventually be calculated from football distributions, not by treating generic PPR points as universally exact.

The initial target bundle does not claim joint component coherence. Independent quantile heads are an initial challenger. A later production artifact should prefer correlated component draws before exact custom scoring and season aggregation.

## Chronological evaluation

Random train/test splits are forbidden.

The benchmark uses expanding whole-season holdouts. With the default 2015-2025 evidence window and four training seasons, evaluation begins in 2019 and moves forward one complete season at a time.

For every held-out year, all model fitting and baseline uncertainty estimation use earlier seasons only.

## Baselines

### Prior-season shrunk baseline

For returning players, q50 begins with the exact previous-season total. Uncertainty comes from earlier training residuals, preferably position-specific when support is sufficient.

Players without an exact prior season fall back to the cohort prior.

### Position × rookie prior

Training-only q10/q50/q90 are estimated by position and rookie status with hierarchical fallback to position and then the global training population.

The candidate is compared against whichever transparent baseline has the lower aggregate pinball loss for each target.

## Frozen promotion gate

Before reading the first real historical result, the default gate is frozen as:

- primary endpoint: `fantasy_points_ppr`;
- at least 1% primary mean-pinball improvement over the stronger baseline;
- at least 60% of held-out seasons won on the primary endpoint;
- season-block bootstrap 95% lower confidence bound above zero;
- no scoring component may regress more than 2% in mean pinball;
- no primary position slice may regress more than 3%;
- if at least 75 rookie rows are available, the rookie primary slice may not regress more than 5%.

A failure is a valid scientific result. Thresholds must not be loosened after seeing the first benchmark merely to obtain a promotion.

## Authority

All initial outputs have:

```text
authority = research_challenger_only
automatic_promotion = false
```

Even a passing benchmark only makes the model eligible for manual activation review. It does not write `product_player_values.csv` and cannot turn the Draft Room green by itself.

Before production activation, the project must additionally qualify:

1. a current 2026 roster feature build with complete GSIS identity;
2. a coherent component-to-league scoring simulation boundary;
3. market/ADP coverage required for draft timing;
4. strict readiness for each supported league profile;
5. artifact provenance and durable storage;
6. prospective decision logging through the live draft ledger.

## Reproduction

The full public-data operator can acquire nflverse player stats, weekly rosters and player metadata directly:

```bash
python scripts/run_preseason_season_benchmark.py \
  --acquire \
  --seasons 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025
```

It writes:

- the constructed preseason dataset;
- dataset diagnostics;
- chronological predictions;
- overall, season, position and rookie metrics;
- engine-vs-baseline comparisons;
- the frozen promotion-gate result;
- a run manifest containing source byte counts and SHA-256 hashes, Git SHA, feature family and authority.

The GitHub workflow `Preseason season-distribution benchmark` runs lightweight contract qualification on pull requests and the full historical benchmark only by explicit manual dispatch.
