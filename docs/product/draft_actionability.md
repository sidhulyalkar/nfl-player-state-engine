# Draft qualification vs. candidate-scoped actionability

## Why these are separate

A fantasy league contract can require positions that the production projection engine does not yet model. Kicker and team defense are the clearest current examples.

That makes the **full league model incomplete**, and `LeagueReadinessReport` / `DraftQualificationReport` should continue to say so. The product must not quietly delete those positions from the league just to turn a status badge green.

At the same time, a missing kicker model does not make two otherwise fully supported early-round WR candidates numerically incomparable.

The reliable-board API therefore exposes two different questions:

1. **Qualification:** Is the complete league + projection + live-room state safe enough for the Draft Room to claim a globally qualified recommendation?
2. **Actionability:** Is this explicit current candidate set internally complete enough to compare those candidates under the exact league scoring contract?

The second answer does not override the first.

## Global qualification

Existing `qualification` remains authoritative and fail-closed.

It inherits full-league blockers such as:

- missing required positions;
- missing or duplicate player identities;
- incomplete valuation coverage;
- unscorable projections;
- stale projection artifacts;
- stale live snapshots.

No behavior in the actionability layer removes one of those blockers.

## Candidate scope

`assess_candidate_scope_actionability` receives an explicit candidate set and validates only those player options.

For the reliable-board endpoint the current scope is the first 12 server-ranked candidates.

A candidate scope blocks when:

- candidate identity is missing or duplicated;
- a candidate has no projection row;
- projection identity is duplicated;
- candidate and projection positions disagree;
- the candidate cannot be scored;
- any candidate falls back to generic fantasy points instead of exact league scoring;
- any candidate lacks a valuation median;
- an unsupported required position appears inside the candidate scope.

Market/ADP absence is a caution rather than a value-comparison blocker because it primarily weakens wait/survival timing.

## Unsupported positions outside the scope

If the league requires K/DST but the current candidate scope contains only exactly scored QB/RB/WR/TE players, the scoped report may return:

```text
status = CAUTION
actionable = true
caution = UNSUPPORTED_REQUIRED_POSITIONS_OUTSIDE_SCOPE
```

The global qualification can simultaneously remain:

```text
status = BLOCKED
can_act = false
blocking = MISSING_REQUIRED_POSITIONS
```

This is intentional. The UI can explain that the current comparison is numerically coherent without claiming the entire draft strategy is complete.

## Authority

The API marks this payload:

```json
{
  "authority": "candidate_scope_diagnostic_only",
  "overrides_global_qualification": false
}
```

The first-party Draft Room also records the scoped diagnostic in prospective decision-audit metadata. This lets us evaluate later whether candidate-scope actionability was useful without silently promoting it during the draft.

## What this does not solve

This layer is **not** a K/DST strategy.

Before global qualification can become READY for leagues that start K/DST, the project still needs either:

- qualified specialist K/DST distributions; or
- an explicit, validated alternative authority for those roster slots.

It also does not decide at what draft point an unsupported K/DST slot should change the immediate recommendation. That requires whole-draft opportunity-cost evidence rather than an arbitrary round-number heuristic.

Until then, candidate actionability is an explanatory diagnostic and prospective research signal, not a bypass around league completeness.
