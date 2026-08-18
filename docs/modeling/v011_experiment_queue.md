# v0.11 Evidence-Driven Experiment Queue

This queue is ordered by expected information value, not novelty. Do not begin a lower item merely because it is more interesting to implement.

## P0 — Run the expanding benchmark

**Question:** Where is the current generative engine actually losing accuracy?

**Protocol:** 2023-2025 held out with expanding weekly cutoffs and earlier warm-up history.

**Primary outputs:**

- play-call log loss / Brier;
- team plays MAE;
- pass-rate MAE;
- points MAE;
- carry / target MAE;
- fantasy pinball loss;
- interval coverage;
- weekly and seasonal win rates.

**Decision:** rank the next experiments by the largest stable error contribution, not by narrative appeal.

## P1 — Integrate state-conditioned opportunity into simulated states

**Start only if:** oracle-state allocation beats static recent share overall and does not hide a material carry or target regression.

**Implementation:** replace static target/carry sampling with the v0.11 hierarchical allocator using *simulated* down, distance, field zone, clock, red-zone, and score state.

**Required ablations:**

1. static share;
2. red-zone-only share;
3. full state-conditioned share;
4. full state-conditioned share with each context family removed.

**Negative control:** randomly permute context labels within team-season while preserving player base share. It should not improve replay.

**Promotion signal:** full pregame player opportunity and fantasy pinball improve, not merely oracle-state likelihood.

## P2 — Team pace and drive-volume model

**Start only if:** team plays MAE remains a material bottleneck.

Candidate state:

- neutral seconds per play;
- no-huddle rate;
- opponent pace;
- first-down conversion;
- expected starting field position;
- turnover rate;
- fourth-down go rate;
- score-state pace response;
- rest / travel / roof / surface where point-in-time safe.

Prefer a transparent regularized or tree challenger before sequence models.

**Negative control:** use the same feature set with team identity shuffled within season.

## P3 — Decomposed play-outcome heads

**Start only if:** play volume and opportunity are acceptable but scoring / fantasy conversion remains weak.

Split the empirical outcome sampler into separately calibrated heads:

```text
pressure / sack
completion
air yards
yards after catch
rushing yards
turnover
touchdown
```

This decomposition makes it possible to discover, for example, that yards are calibrated but touchdown tails are not.

Do not collapse these into a single opaque neural outcome model until each head has a simple benchmark.

## P4 — Persistent drive strategy state

**Start only if:** residual analysis shows within-drive serial structure after down/distance/score conditioning.

Candidate latent states:

- SCRIPTED;
- NORMAL;
- HURRY_UP;
- CLOCK_CONTROL;
- COMEBACK;
- RED_ZONE_PACKAGE.

Model state transitions at drive/play boundaries and evaluate whether persistent state improves play-family calibration and team volume.

**Negative control:** randomly rotate latent-state labels across drives after fitting.

## P5 — Formation, personnel, route, and alignment evidence

**Start only when point-in-time source availability is proven.**

Priority:

1. routes / pass-play participation;
2. personnel packages;
3. alignment;
4. motion;
5. play action / RPO / screen concepts;
6. first-read or concept proxies if legitimately obtainable.

Retrospective charting may be used for representation research but cannot silently enter historical live replay.

## P6 — Offensive-line and defensive-response state

Potential evidence:

- OL starter continuity;
- position-specific replacements;
- pressure allowed;
- defensive front proxy;
- box count;
- blitz / pressure tendency;
- shell / coverage proxies where available.

Target mechanism:

```text
OL + defensive response
    -> pressure distribution
    -> time to throw / scramble / sack
    -> depth of target
    -> receiver opportunity and efficiency
```

Test the mechanism in that order rather than adding a single "matchup grade" feature.

## P7 — Coaching adaptation

The existing direct play-caller matchup prior remains heavily shrunk.

Next measurable coaching questions:

- how quickly does a play caller abandon an unsuccessful family?
- how persistent are opening-script concepts?
- does second-half behavior respond consistently to first-half success?
- how aggressively does pace change with score state?
- how stable are red-zone and third-down packages?

Treat these as observable policy parameters, not personality inference.

## P8 — Environmental and market sensors

Candidate evidence:

- 48h / 24h / 6h / kickoff weather trajectory;
- roof decision;
- surface;
- travel and rest;
- official crew penalty environment;
- market implied team totals / spreads.

Market disagreement should first be used as a diagnostic trigger:

```text
large model-market disagreement
    -> inspect which model layer differs
    -> compare calibration historically
```

Do not automatically blend market numbers into the football model.

## P9 — Representation learning

Only after the simpler causal heads establish useful residual structure should we test:

- play-sequence encoders;
- drive-state embeddings;
- team / coach temporal embeddings;
- graph representations over player-team-coach-opponent state;
- tracking-derived representations.

Any deep representation must beat the simple frozen baselines and survive cross-season / team transfer tests.

## Weekly season loop

Every completed week should produce:

```text
frozen prediction archive
    + realized game
    + layer-specific residual ledger
    + challenger experiments
    + replay report
    + registry entry
```

The experiment queue can then be re-ranked using actual error evidence. The project should evolve toward the failure mode the season reveals, not toward a fixed pre-season architecture diagram.
