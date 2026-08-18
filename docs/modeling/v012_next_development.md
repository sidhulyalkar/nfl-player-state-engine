# v0.12 → v0.13 Evidence Router

Do not choose v0.13 by novelty. Use the v0.12 factorial report to identify which model layer is still preventing downstream improvement.

## Decision map

### Pattern A — State allocation improves opportunity and fantasy loss

```text
learned_state player opportunity < learned_static
AND
learned_state fantasy pinball <= learned_static
```

**Next:** richer role and route-state evidence.

Priority inputs:

1. route participation / routes run;
2. alignment and personnel package;
3. slot / wide / backfield usage;
4. third-down role;
5. two-minute role;
6. goal-line package;
7. motion / play-action / RPO context when point-in-time safe.

The next model should predict conditional opportunity, not generic player quality.

### Pattern B — Context wins with realized states but loses in full simulation

```text
full oracle-state log loss < static share
BUT
learned_state full-pregame opportunity >= learned_static
```

**Next:** pace and drive-state realism.

This pattern means player context contains signal, but the simulator is visiting the wrong states or visiting them at the wrong frequency.

Build a transparent team-volume model around:

- neutral seconds per play;
- score-state pace changes;
- no-huddle probability;
- first-down conversion;
- drive continuation;
- starting field position;
- turnovers;
- fourth-down continuation;
- opponent pace.

### Pattern C — Play-call log loss improves, team plays do not

**Next:** pace / drive volume, not another run-pass classifier.

Run/pass choice does not determine how many possessions or snaps a game produces. Add a drive-level volume challenger before adding more play-call features.

### Pattern D — Opportunity improves, scoring/fantasy does not

**Next:** decomposed play outcomes.

Replace the coarse empirical outcome sampler one head at a time:

```text
pressure / sack
completion
air yards
YAC
rushing yards
turnover
touchdown conversion
```

Evaluate each head separately and keep correlated simulation draws.

### Pattern E — Full context cannot beat the permuted negative control

**Next:** reject or redesign the context model.

Do not add more context dimensions. Investigate:

- sparse contexts;
- role churn;
- stale player eligibility;
- coach/team identity confounding;
- overly long lookback;
- context definitions that merely proxy base share.

### Pattern F — Results are unstable by season/week

**Next:** evidence quality and regime segmentation.

Break out:

- coaching changes;
- QB changes;
- injuries / role transitions;
- early season vs established role;
- favorites vs underdogs;
- high-total vs low-total games;
- stable vs unstable depth charts.

A model that only wins after role stabilization may still be useful if its authority is conditioned on evidence maturity.

## Later architecture, only after the simple heads justify it

Potential v0.14+ directions:

- persistent drive strategy states;
- offensive-line continuity and pressure path;
- defensive front / shell response;
- route and alignment graph state;
- halftime adaptation parameters;
- learned team / coach temporal embeddings;
- play-sequence encoders;
- tracking-derived representations.

The governing rule remains:

```text
new representation
    -> isolated frozen benchmark
    -> negative control
    -> full downstream replay
    -> promotion gate
```

No architecture earns authority because it is more sophisticated.
