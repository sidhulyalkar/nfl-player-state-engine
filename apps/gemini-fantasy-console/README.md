# Fourth Down Lab: Gemini Fantasy Console

A React + Node full-stack frontend for the NFL Player State Engine. It is designed for Google AI Studio Build mode, local Vite development, or Cloud Run.

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

The UI includes demo data when the Product API has no imported league yet.

## Google AI Studio

Import the repository from GitHub into Build mode or paste `ai_studio/BUILD_PROMPT.md`. Add `PSE_API_BASE_URL` and `GEMINI_API_KEY` as server-side secrets. See `docs/product/gemini_ai_studio.md`.
