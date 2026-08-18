# Ranking Calibration Architecture — v0.9

## The target is not consensus rank

The system's production objective is eventually **expected marginal draft utility**, not agreement with an expert list.

For player `p` at decision time `t`:

```text
U(p, t) = E[value of best achievable roster | draft p now]
        - E[value of best achievable roster | do not draft p now]
```

v0.9 does not claim to solve that full equation yet. It creates the measurable layers required to get there without confusing projection, league value, market timing and outside opinion.

## Layer 1: football outcome distribution

Predict football components and correlated outcomes before fantasy scoring whenever possible.

Examples:

- QB: attempts, passing yards/TD/INT, designed rushes, scrambles, rushing yards/TD;
- RB: carries, routes, targets, receptions, yards, goal-line work;
- WR/TE: routes, targets, catches, receiving yards, air-yard/TD states;
- availability and role security remain separate latent states.

## Layer 2: exact league scoring

Preferred:

```text
correlated football draws
  -> score every draw under LeagueConfig
  -> aggregate fantasy distribution
```

Supported fallback:

```text
complete football component quantiles
  -> deterministic league rescore
```

Compatibility fallback:

```text
generic fantasy-point quantiles
  -> explicit generic_points_fallback
```

The third path is not called scoring-exact.

## Layer 3: replacement economy

Starter demand is derived from the actual roster slots. Fixed seats are allocated first; flex/superflex seats are allocated to whichever eligible next player has the highest league-scored projection.

Replacement ranks and VORP therefore respond to:

- team count;
- 1QB / 2QB / superflex;
- WR/RB/TE depth;
- number of flex seats;
- scoring system;
- projection curve.

## Layer 4: positional curve

v0.9 adds diagnostics beyond within-position relative VORP:

- position projection rank;
- players remaining above replacement;
- replacement slope;
- next-player VORP drop;
- dynamic scarcity score.

These characterize the shape of the supply curve rather than awarding every position a normalized top score of 1.0.

## Layer 5: draft-room opportunity cost

For each available player, the live board estimates:

- probability the player survives to the next manager pick;
- remaining same-position positive-VORP supply;
- expected same-position selections before the next turn;
- expected same-position supply at the next turn;
- probability-weighted value of the best same-position alternative likely to survive;
- `position_wait_loss`.

This supports the question:

> If I pass QB4, what value do I realistically expect to retain at quarterback by my next pick?

## Production vs challenger

`live_draft_score` remains production in v0.9.

The new `ranking_challenger_score` is deliberately unpromoted and uses dynamic wait-loss information. This allows a clean historical comparison rather than editing production coefficients until a few examples look attractive.

## External calibration

Expert and market snapshots are normalized into a common point-in-time schema.

They are used for:

- model-versus-consensus disagreement;
- expert dispersion;
- format transformation audits;
- cross-market ADP dispersion;
- survival-model features;
- investigation queues.

They are **not** used as the football target.

## Format-delta validation

Absolute correlation asks:

```text
Does our rank resemble expert rank?
```

Format-delta correlation asks a more useful question:

```text
When 12-team 1QB becomes 12-team 2QB,
do players move in a similar direction and magnitude?
```

For player `i`:

```text
model_delta_i    = model_rank_i(format_B) - model_rank_i(format_A)
external_delta_i = external_rank_i(format_B) - external_rank_i(format_A)
```

Then inspect Spearman/Kendall agreement between those deltas.

External agreement remains diagnostic. Historical roster utility remains the promotion objective.

## Structural tests

The format matrix contains assertions that should hold independent of external rankings, including:

- 2QB consumes materially more QBs than equivalent 1QB;
- superflex consumes more QBs than equivalent 1QB when the QB projection curve warrants it;
- expanded 8-team 2QB consumes more QBs than expanded 8-team 1QB;
- PPR raises receiving-position fantasy points when component scoring is exact;
- TE premium raises TE fantasy points when component scoring is exact.

Scoring-related checks **SKIP rather than PASS** when generic fantasy-point fallback prevents a valid test.

## Historical replay

The historical decision table should contain rows such as:

```text
draft_id
current_pick
player_id
production_score
challenger_score
frozen_utility_target
```

Every row must represent a player genuinely available at that timestamp.

`draft_ranking_replay.py` selects each policy's top candidate within the same decision set and reports utility and oracle regret.

A future stronger utility target can be:

- rest-of-season optimal-starter contribution;
- weekly team points added;
- median-win delta;
- playoff-probability delta;
- championship-probability delta.

Do not use information that was unavailable at the historical draft time to construct the score columns.

## Two-turn planner

The research `two_turn_survival_lookahead_research_v1` simulates which other players survive to the manager's next selection and adds the best surviving value to the current candidate's value.

It provides:

- expected next-pick value;
- expected two-pick value;
- q10/q50/q90 two-pick value;
- probability no preferred target survives;
- most common next targets.

It intentionally does **not** yet model:

- every opponent's roster-conditioned pick policy;
- roster-fit reoptimization after every intervening selection;
- correlated positional runs;
- pick trades;
- full-season team simulation at every branch.

Therefore it is research-only in v0.9.

## Promotion gate

A ranking challenger earns production authority only when:

```text
structural format tests       PASS
point-in-time data integrity  PASS
historical utility vs baseline improves
oracle regret does not worsen materially
calibration/provenance         acceptable
CI                             PASS
```

An installed model or clever formula is not a promotion criterion.
