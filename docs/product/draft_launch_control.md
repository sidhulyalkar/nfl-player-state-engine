# Draft Launch Control

Draft Launch Control is the final current-state preparation boundary before opening the live Draft Room.

It is intentionally **not** a release or model-management surface. It has no model-training, artifact-registry, production-approval, or champion-promotion dependency.

## Operator flow

Use the Draft Room in this order:

1. **Real Leagues**: declare the intended league count and connect every real Sleeper/ESPN league.
2. **Draft Launch**: click **Prepare Draft Room** shortly before the draft.
3. **Draft-Day Doctor**: read the resulting `READY`, `PROVISIONAL`, or `BLOCKED` verdict and active remediation.
4. **Live board**: use only the league surfaces whose Doctor contract remains usable.

The launch action refreshes only mutable current-state inputs:

- observational NFL Hub state;
- connected real league rules, rosters, ownership, and platform draft state;
- K/DST `external_market_only` guidance when a connected league requires those slots;
- FantasyPros live ADP timing when a server-side API key is configured.

It then re-runs the portfolio-aware Draft-Day Doctor.

## Authority contract

Every launch response explicitly reports:

```text
authority=current_state_refresh_only
champion_mutated=false
model_promotion_performed=false
```

The launch service cannot approve a challenger, move a champion pointer, retrain a model, change scoring contracts, or rewrite projection bytes.

A source refresh failure is not silently promoted to success. The stage is reported as one of:

- `REFRESHED`: a new validated current-state snapshot was installed;
- `PRESERVED`: refresh failed but a prior valid snapshot remains for Doctor evaluation;
- `SKIPPED`: the source is not required or not configured;
- `FAILED`: refresh failed and no valid prior state is available.

The Doctor verdict remains authoritative after those stage outcomes. A successful refresh operation does not override a `BLOCKED` or `PROVISIONAL` Doctor result.

## API

```text
GET  /v1/draft/launch/status
POST /v1/draft/launch/prepare?season=2026
```

Concurrent prepare requests in one API process are rejected with HTTP 409. This prevents accidental double refreshes from repeated clicks.

## Draft-night recovery

If the browser has a problem, the Product API remains inspectable directly. Check `/v1/draft/launch/status` and `/v1/draft/doctor`. Individual source refresh commands also remain available, including `scripts/refresh_special_teams_market.py`.

Never manufacture league state, ADP, injury information, K/DST model values, or projection authority to make the launch screen green.
