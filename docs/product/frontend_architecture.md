# Frontend and service architecture

## Recommended architecture

```text
Fantasy platforms and CSV exports
             │
             ▼
     Platform adapters
 Sleeper / Yahoo / Fleaflicker / CSV
             │
             ▼
    Canonical LeagueSnapshot
             │
      ┌──────┴─────────┐
      ▼                ▼
Player State Engine   League store
projections/sims      snapshots/history
      │                │
      └──────┬─────────┘
             ▼
       FastAPI Product API
 deterministic tools and contracts
             │
      ┌──────┴───────────────┐
      ▼                      ▼
React visual application   Node Gemini BFF
charts, tables, scenarios  function calling
      │                      │
      └──────────┬───────────┘
                 ▼
             End user
```

## Why split Node and Python?

Google AI Studio Build mode provides a React client and Node server runtime. The Player State Engine is already Python-native and should remain responsible for model inference, optimization, and simulation. The Node layer is a thin backend-for-frontend that:

- protects the Gemini API key;
- converts user language into deterministic tool calls;
- proxies requests to the Python Product API;
- can own Firebase authentication and user preferences;
- never recomputes football values independently.

## Product API boundaries

Implemented in `src/player_state_engine/api/app.py`:

- `GET /health`
- `GET /v1/leagues`
- `POST /v1/integrations/sleeper/import`
- `POST /v1/leagues/snapshot`
- `GET /v1/leagues/{league_id}`
- `GET /v1/leagues/{league_id}/players`
- `GET /v1/leagues/{league_id}/power-rankings`
- `GET /v1/leagues/{league_id}/waivers`
- `GET /v1/leagues/{league_id}/lineup`
- `POST /v1/trades/analyze`
- `GET /v1/leagues/{league_id}/trades/suggestions`
- `GET /v1/nfl/state`
- `GET /v1/copilot/context/{league_id}`

## Persistence evolution

### Prototype

- League snapshots: versioned JSON
- Model artifacts: Parquet and joblib
- User preferences: browser local storage or Firestore

### Beta

- PostgreSQL: users, leagues, rosters, transactions, recommendations
- Object storage: immutable model and prediction artifacts
- Redis: current-week cache and background-job state
- Firestore can remain useful for lightweight UI preferences and collaboration

### Production

- Event-sourced league snapshot history
- Feature store with timestamped source validity
- Queue-driven imports and weekly model refreshes
- Separate read-optimized player and league views

## Security requirements

- Gemini and platform credentials are server-side only.
- OAuth refresh tokens must be encrypted at rest.
- League data are private by default.
- No platform password collection.
- No login-bypassing scraping.
- Validate every Gemini tool argument against server schemas.
- Rate-limit import, copilot, and simulation endpoints.
- Maintain an audit log of tool calls and recommendations.

## Performance targets

- League dashboard cached response: under 400 ms p95
- Player search: under 150 ms p95
- Trade analysis: under 1 second for a selected proposal
- Suggested-trade search: under 5 seconds or asynchronous with progress
- Gemini explanation after tool results: under 8 seconds p95
- Weekly league sync: under 30 seconds for Sleeper
