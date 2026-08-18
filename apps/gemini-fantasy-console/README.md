# Fourth Down Lab: Gemini Fantasy Console

A React 19 + Express 5 full-stack frontend for the NFL Player State Engine. It is designed for the Google AI Studio Node.js 22 runtime, local development, or Cloud Run.

## Current product priority

The next frontend milestone is the **Draft War Room**: a live multi-league workspace for comparing 2 to 5 available players under the exact scoring, roster construction, current roster, positional scarcity, and pick timing of the active draft.

Read:

```text
docs/product/draft_war_room_frontend.md
docs/modeling/draft_intelligence_models.md
ai_studio/DRAFT_WAR_ROOM_PROMPT.md
```

The Draft War Room must distinguish four concepts instead of hiding them in one ranking:

- raw football projection;
- league-specific inherent value / replacement scarcity;
- fit into the user's current roster;
- cost of waiting until the user's next pick.

This distinction is mandatory for 2QB and superflex formats.

## Responsibilities

- React renders league, draft, player, trade, waiver, lineup, NFL-state, and model-trust views.
- The Node server keeps `GEMINI_API_KEY` private and proxies the Python Product API.
- Gemini performs tool selection, comparison, and explanation only.
- The Python engine remains authoritative for projections, draft scarcity, VORP, roster utility, optimization, simulation, and trade evaluation.
- The deterministic product remains usable if Gemini is disabled.

## Local start

```bash
# Terminal 1, repository root
python -m pip install -e ".[api]"
python -m player_state_engine.api

# Terminal 2
cd apps/gemini-fantasy-console
npm install
cp .env.example .env
npm run dev
```

Express listens on `0.0.0.0:3000` by default and mounts Vite as development middleware. In production it serves the compiled React application, including the SPA route fallback, from the same process. The UI includes clearly labeled synthetic fixtures when the Product API has no imported league yet.

## Evidence-aware product surfaces

- Persistent `SYNTHETIC DEMO`, `HISTORICAL BACKTEST`, `STALE`, or `LIVE` provenance
- Model version, prediction timestamp, feature cutoff, identity coverage, and missing-input warnings
- Decision-specific player rankings with overall and positional ranks, VORP, search, sorting, and CSV export
- Live draft room state with current/next pick and candidate comparison as the next implementation milestone
- Roster-relative waiver and legal-lineup endpoints
- League positional-needs heatmap and two-sided trade deltas
- Frozen historical prediction replay and experiment-gate results
- Lagged team-context fingerprints separated from observed standings

Gemini explains deterministic Product API results. When `GEMINI_API_KEY` is absent, the server should still route lineup, waiver, trade, draft, and ranking questions to the corresponding Product API tool and return a labeled structured fallback.

## Google AI Studio

Import the repository from GitHub into Build mode. Use:

- `ai_studio/BUILD_PROMPT.md` for the whole product;
- `ai_studio/DRAFT_WAR_ROOM_PROMPT.md` for the current milestone.

Add `PSE_API_BASE_URL` as a server-side environment value. Keep `GEMINI_API_KEY` server-side only. See `docs/product/gemini_ai_studio.md`.

Do not ask AI Studio/Gemini to recreate Python numerical formulas in TypeScript. If a server-side draft metric is not yet exposed, show it as unavailable and add the appropriate Product API contract rather than inventing a browser implementation.
