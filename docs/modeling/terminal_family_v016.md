# v0.16 Terminal-Family Generation Contract

## Purpose

v0.16 tests the missing mechanism between the v0.15 binary drive-termination diagnostic and a coherent generative possession state machine.

The target is not generic "drive ends." It is the canonical family following an offensive scrimmage play:

- `CONTINUE`
- `SCORE`
- `TURNOVER`
- `DOWNS`
- `END_HALF`

All v0.16 authority is research-only. The live simulator and production projections remain unchanged.

## Why the v0.15 hazard is not enough

A binary hazard can learn that a possession is likely to end without knowing how it ends. Giving that hazard direct simulator authority would force the simulator to invent an event type after the fact. That can create incoherent score, turnover, yardage, and player-stat combinations.

v0.16 therefore decomposes the problem:

```text
observable state
      |
      v
P(possession ends)
      |
      +-- CONTINUE
      |
      v
P(terminal family | ends)
      |
      +-- SCORE
      +-- TURNOVER
      +-- DOWNS
      +-- END_HALF
```

The hazard and conditional-family heads are scored separately as well as jointly.

## Canonical labeling boundary

The generative target is deliberately different from the v0.15 "final scrimmage play of drive" diagnostic.

A failed third-down play followed by a punt or field-goal attempt is **not terminal** for v0.16. It is `CONTINUE`, because fourth-down action policy still owns the next event.

A scrimmage play is terminal when it directly creates one of these families:

1. `TURNOVER`: interception, lost fumble, or other offensive turnover;
2. `SCORE`: offensive touchdown, unless the play is already classified as a turnover;
3. `DOWNS`: failed fourth-down scrimmage attempt;
4. `END_HALF`: final eligible possession event before halftime or game end, after higher-priority terminal outcomes are excluded;
5. otherwise `CONTINUE`.

This ordering prevents a late interception from being mislabeled `END_HALF` merely because no later play follows it.

## Point-in-time evidence

Every weekly fold trains only on chronology strictly before the held-out `(season, week)` cutoff. No test-week terminal label, terminal distribution, or outcome row enters training.

The terminal model uses transparent recency-weighted empirical shrinkage over:

- team;
- down;
- field zone;
- distance bucket;
- clock bucket;
- score state;
- play family;
- end-of-half/game window.

The model is intentionally interpretable. Deep sequence models are not justified until this layer survives replay and residual serial dependence remains.

## Baselines and negative controls

The model must beat multiple easier explanations.

### Observable-state baselines

- global terminal distribution;
- team base;
- context base;
- canonical binary hazard baseline.

### Full-family permutation

Terminal labels are permuted within `(season, down bucket, field zone)`. This preserves broad family marginals while breaking finer team/time/score/play-family mapping.

### Conditional-family permutation

Only terminal type is permuted among already-terminal rows. Exact termination labels remain unchanged. This tests whether the second-stage family head adds signal beyond merely knowing a possession ends.

## Structural support during generation

Simulator authority cannot create impossible terminal families just because an empirical cell is sparse.

- `DOWNS` has zero generative support unless the current play is fourth down.
- `END_HALF` has zero generative support unless the game clock is inside a short structural boundary window.

These constraints apply to authority, not retrospective scoring. Historical oddities remain visible during evaluation rather than being silently erased.

## Historically coherent outcome generation

v0.16 does not convert a class label directly into fake stats.

`EmpiricalPlayOutcomeModel` gains an additive terminal index over the same pre-cutoff outcome rows. After a terminal family is selected, the simulator samples an observed outcome row compatible with:

- play family;
- terminal family;
- down / distance / field zone where sufficient support exists.

Fallback is to a broader play-family × terminal-family pool. If no compatible pool exists, the challenger falls back to the frozen legacy outcome and records the fallback.

A high fallback rate fails the v0.16 gate.

## Common-random-number contract

Terminal authority must not obtain artificial lift by shifting unrelated Monte Carlo streams.

For every simulated scrimmage play:

1. the exact frozen v0.15 empirical outcome draw is still consumed from the legacy outcome RNG;
2. its pre-draw RNG state is hashed into deterministic shadow streams;
3. the challenger samples terminal family and terminal-conditioned outcome from those shadow streams;
4. shadow streams do not advance the legacy outcome RNG;
5. when conditioning succeeds, the frozen outcome is discarded;
6. when conditioning fails, the frozen outcome is used.

This preserves the established RNG trajectory for future legacy draws while allowing the intervention itself to differ.

## END_HALF clock coupling

`END_HALF` is not represented as a turnover or score. When it receives authority, the terminal-aware pace wrapper advances the clock to the actual halftime/game boundary. The existing v0.15 state machine then performs its ordinary halftime transition.

This keeps the clock mechanism separate from terminal football outcomes.

## Eight-cell factorial replay

v0.16 runs every combination of:

- possession transition authority: legacy / learned;
- fourth-down decision authority: legacy / learned;
- terminal-family authority: legacy / learned.

That yields eight cells. Terminal authority is compared within four parent contexts, so it cannot earn promotion by working only when stacked on every previous challenger.

## Required evidence before research-champion review

Default gate requirements include:

- at least three held-out seasons;
- at least 200 replay games;
- sufficient full and conditional terminal samples;
- joint terminal-family log loss beats context baseline by a preregistered margin;
- joint model beats full permutation;
- conditional-family head beats conditional permutation;
- calibration ECE below the safety ceiling;
- conditioned-outcome fallback rate below 1%;
- terminal event frequency improves in at least three of four parent contexts;
- weekly consistency;
- no material regression in drives, plays, pace, scoring, opportunity, fantasy, punts, field goals, or fourth-down decisions.

Passing the gate means only **eligible for manual research-champion review**.

It does not change production projections, the live API simulator, or any default fantasy recommendation.

## Known limitations

v0.16 still does not model:

- causal execution heads for completion, pressure, rushing efficiency, or touchdown conversion;
- player-level return outcomes;
- overtime;
- PAT / two-point strategy;
- explicit timeout strategy;
- latent persistent drive strategy;
- coach/QB/weather terminal-family interactions beyond existing observable state.

Those become candidate v0.17 branches only if replay evidence isolates them as bottlenecks.
