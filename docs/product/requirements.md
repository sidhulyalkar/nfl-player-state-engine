# Product requirements document

## Objective

Create the most useful fantasy football analysis workspace for serious managers by combining calibrated player distributions, complete league state, deterministic optimization, and evidence-grounded Gemini assistance.

## MVP release criteria

### League onboarding

- Sleeper league import by league ID
- Generic CSV import
- Multiple saved leagues
- Accurate scoring and roster-slot normalization
- Ownership and free-agent coverage report
- Manual identity-resolution queue

### Player data

- Current weekly q10/q50/q90
- Rest-of-season q10/q50/q90
- Availability and opportunity confidence
- Owner or free-agent state
- Decision-specific league value
- Reason codes and prediction timestamp

### Decisions

- Legal lineup optimization
- Roster-relative waiver ranking
- Trade analysis for both teams
- Suggested one-for-one and two-for-one trades
- League power rankings
- NFL standings endpoint

### Frontend

- Eight primary views defined in the information architecture
- Demo mode
- API error and stale-data states
- Gemini tool-calling drawer
- Responsive desktop and mobile layouts
- Exportable player board

### Trust

- Model version and prediction time displayed
- Missing-source warnings
- No Gemini claim without a tool result for league-specific questions
- No automatic transactions
- Recommendation audit log specification

## Beta requirements

- Yahoo OAuth integration
- Fleaflicker normalization
- Platform transaction and matchup history
- Firestore or Postgres persistence
- Correlated season/playoff simulation
- Acceptance-aware counteroffers
- User decision and outcome tracking
- Push/email alerts
- Background league refresh

## Production requirements

- Multi-tenant authentication and authorization
- Encrypted OAuth tokens
- Durable queues and scheduled jobs
- Observability, error budgets, and rate limiting
- Model registry integration
- Full source and recommendation provenance
- Billing and plan enforcement
- Data retention and deletion controls

## Non-functional requirements

- Read-only platform access in the first product release
- P95 dashboard response under 400 ms from cache
- P95 selected trade analysis under 1 second
- WCAG-conscious contrast and keyboard support
- No silent player drops during identity resolution
- Deterministic results for identical model, league, and cutoff inputs
