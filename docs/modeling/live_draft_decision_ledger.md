# Live Draft Decision Ledger

## Purpose

A draft model cannot be validated from memory after the season. The live product must freeze what it actually recommended, what alternatives were visible, and whether the state was operationally qualified at that moment.

The Decision Console therefore requests an audit checkpoint whenever it loads the reliable live board. The server owns the numerical snapshot; the browser does not submit reconstructed scores.

## Storage

The default ledger is:

```text
data/product/decision_audit/draft_decisions.jsonl
```

Override it with:

```text
PSE_DRAFT_DECISION_AUDIT_PATH
```

Each line is a `DecisionAuditRecord` containing:

- stable decision ID;
- UTC capture time;
- league and exact league contract;
- current pick, next pick, draft slot, roster and drafted-player state;
- the top visible candidate set;
- production recommendation and action;
- production and room-challenger values where available;
- survival probabilities;
- reliability score and reasons;
- live draft qualification state;
- projection provenance;
- draft-survival artifact metadata;
- explicit research-authority metadata.

## Deduplication

The decision ID is derived from league identity plus the canonical draft-state key. Polling the same room state every ten seconds therefore does not create repeated observations.

When a new pick changes the room state, the state key changes and a new observation is written.

The API reports one of:

- `RECORDED`: a new state was appended;
- `DEDUPLICATED`: the exact state was already present;
- `FAILED`: capture was requested but persistence failed;
- `DISABLED`: the caller chose not to request capture.

The reliable-board API itself defaults `capture_audit=false` so read-only API consumers retain ordinary GET semantics. The first-party Draft Room client explicitly requests capture by default.

## Blocked states are evidence too

A `BLOCKED` draft qualification is still recorded.

This is deliberate. Later evaluation must be able to distinguish:

```text
model preferred Player A
```

from:

```text
model preferred Player A, but the system explicitly blocked action because the projection artifact was stale
```

Blocked observations are not counted as qualified production actions unless a later replay contract explicitly chooses to study them.

## Settlement

`settle_draft_decision_regret()` already limits hindsight comparison to alternatives that were visible in the frozen candidate set at decision time.

The next replay layer should settle this ledger against a preregistered utility definition and compare policies such as:

- ADP-only;
- projected-points-only;
- VORP-only;
- production live draft score;
- production score plus promoted empirical survival;
- roster-simulator challenger.

Results must be sliced by league format. A pooled win cannot authorize a policy that materially regresses the 8-team 2QB expanded or 12-team median-scoring environments.

## Authority boundary

The ledger is evidence capture, not model promotion.

Recording a room challenger, research score, or blocked recommendation does not make it authoritative. Promotion remains governed by the relevant frozen replay and evidence gates.
