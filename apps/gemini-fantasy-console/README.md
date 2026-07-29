# Fourth Down Lab: Gemini Fantasy Console

A React 19 + Express 5 full-stack frontend for the NFL Player State Engine. It is designed for the Google AI Studio Node.js 22 runtime, local development, or Cloud Run.

## Responsibilities

- React renders league, player, trade, waiver, lineup, NFL-state, and model-trust views.
- The Node server keeps `GEMINI_API_KEY` private and proxies the Python Product API.
- Gemini performs tool selection and explanation only.
- The Python engine remains authoritative for projections, optimization, simulation, and trade evaluation.

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

- Persistent `SYNTHETIC DEMO`, `HISTORICAL BACKTEST`, or `LIVE` provenance
- Model version, prediction timestamp, feature cutoff, identity coverage, and missing-input warnings
- Decision-specific player rankings with overall and positional ranks, VORP, search, sorting, and CSV export
- Roster-relative waiver and legal-lineup endpoints
- League positional-needs heatmap and two-sided trade deltas
- Frozen historical prediction replay and experiment-gate results
- Lagged team-context fingerprints separated from observed standings

Gemini explains deterministic Product API results. When `GEMINI_API_KEY` is absent, the server can still route lineup, waiver, trade, and ranking questions to the corresponding Product API tool and returns a labeled structured fallback.

## Google AI Studio

Import the repository from GitHub into Build mode or paste `ai_studio/BUILD_PROMPT.md`. Add `PSE_API_BASE_URL` and `GEMINI_API_KEY` as server-side secrets. See `docs/product/gemini_ai_studio.md`.
