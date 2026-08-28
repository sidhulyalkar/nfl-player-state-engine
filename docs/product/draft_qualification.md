# Live Draft Qualification

## Purpose

The Draft Room must answer two different questions without conflating them:

1. **Who is the best player to select?**
2. **Is the system currently safe to act on?**

Player ranking, VORP, room survival, roster fit, and uncertainty answer the first question. `DraftQualificationReport` answers the second.

The qualification verdict is server-owned. React displays it but does not recompute it.

## Statuses

### `READY`

The league input audit has no blocking findings, the production projection artifact is within the configured freshness window, the live league snapshot is within its stale window, and there are no soft readiness cautions.

`can_act = true`.

### `CAUTION`

There are no hard blockers, but one or more non-blocking limitations deserve attention. Examples include low market coverage, generic scoring fallback, or a live refresh warning while the currently mounted snapshot is still fresh.

`can_act = true`, but the UI must display the caution reason.

### `BLOCKED`

At least one condition makes a live recommendation unsafe to treat as current. Examples include:

- stale production projections;
- missing production projection artifact;
- stale live league/draft snapshot;
- missing required positions;
- missing or duplicate player identity;
- unscorable projections;
- incomplete valuation coverage;
- readiness score below the configured minimum.

`can_act = false`.

A blocked Draft Room may still render historical or diagnostic information, but its recommendation must not be presented as a qualified live action.

## Why projection and room freshness are separate

Projection freshness and room freshness fail for different reasons.

A projection artifact can be old even when the platform sync is perfect. In that case the board knows the current picks but is valuing them with stale football information.

A league snapshot can be old even when projections are fresh. In that case player values may be current but completed picks, roster construction, positional runs, and turn timing may no longer match the room.

Either stale condition blocks live action.

## API

The reliable draft-board endpoint returns:

```text
GET /v1/leagues/{league_id}/draft/reliable-board
```

with an additive `qualification` object:

```json
{
  "status": "READY",
  "can_act": true,
  "blocking_reasons": [],
  "caution_reasons": [],
  "league_inputs_ready": true,
  "projection_fresh": true,
  "live_snapshot_fresh": true,
  "refresh_healthy": true,
  "readiness_score": 94.2,
  "projection_age_hours": 2.1,
  "max_projection_age_hours": 24.0,
  "snapshot_age_seconds": 8.4,
  "stale_after_seconds": 60.0
}
```

The existing static `readiness` object remains available separately. This preserves the distinction between league-input health and live operational qualification.

## UI

The Decision Console surfaces the qualification verdict in two places:

- the top state badge;
- the trust card beside the primary recommendation.

The Trust Layer also lists the exact blocking or caution reason. The browser formats server-owned reason codes for readability but does not decide whether a condition is blocking.

## Operational thresholds

`max_projection_age_hours` defaults to 24 hours on the reliable-board endpoint and can be lowered for a draft-day deployment.

The live league stale window is controlled by:

```text
PSE_DRAFT_STALE_SECONDS
```

and defaults to 60 seconds.

For an active draft, a deployment should prefer aggressive refreshes over relaxing the stale threshold.

## Research authority

Draft qualification does not promote research challengers.

A `READY` verdict means the current **production-authoritative** inputs are operationally qualified. It says nothing about whether the Player State Graph, room simulation challenger, availability experiment, terminal-family model, or another research layer has earned production authority.

Those promotion decisions continue to require their own frozen evidence contracts.

## Weekly refresh regression contract

The scheduled weekly model refresh runs the full Python test suite before updating challengers. Because API tests are part of that suite, its environment must include the `api` optional dependency.

The workflow therefore installs:

```bash
python -m pip install -e ".[dev,intelligence,api]"
```

A regression test asserts that exact capability contract so the scheduled workflow cannot drift back to an environment that fails test collection before refresh work begins.
