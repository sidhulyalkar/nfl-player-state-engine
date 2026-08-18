# Fourth Down Lab: Gemini Fantasy Console

A React 19 + Express 5 full-stack frontend for the NFL Player State Engine. It is designed for the Google AI Studio Node.js 22 runtime, local development, or Cloud Run.

## Operational Draft War Room

v0.8 makes the **Draft War Room** the primary frontend surface. It is a live multi-league workspace for comparing 2 to 5 available players under the exact scoring, roster construction, current roster, positional scarcity, and pick timing of the active draft.

The browser consumes authoritative Python endpoints:

```text
GET  /v1/draft/leagues
GET  /v1/leagues/{league_id}/draft/board
POST /v1/leagues/{league_id}/draft/compare
```

The War Room separates four concepts instead of hiding them in one ranking:

- raw football projection;
- league-specific inherent value / replacement scarcity;
- fit into the user's current roster;
- cost of waiting until the user's next pick.

This distinction is mandatory for 2QB and superflex formats. The compare endpoint additionally runs server-side quantile roster counterfactuals, re-optimizing legal starters for every simulated draw.

Read:

```text
docs/product/draft_war_room_frontend.md
docs/modeling/draft_intelligence_models.md
docs/modeling/draft_survival_training.md
ai_studio/DRAFT_WAR_ROOM_PROMPT.md
```

## Live behavior

While a draft is active, React conservatively polls the Product API and cancels obsolete requests. New completed picks are canonicalized, removed from the available board, and trigger fresh league-value, roster-need, tier-cliff, and next-pick calculations. Manual force refresh is always available.

The UI preserves the last valid board when a platform refresh fails and shows freshness / stale-state warnings instead of fabricating replacement data. Sleeper refreshes reuse the server-side player-map cache; ESPN is polled more conservatively.

Draft survival uses a transparent normal-ADP approximation by default. A trained empirical artifact can replace it only after grouped held-out historical drafts show a Brier-score improvement over that baseline. An installed but unpromoted artifact is displayed as such and is not allowed to modify the live recommendation.

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
npm ci
cp .env.example .env
npm run dev
```

Express listens on `0.0.0.0:3000` by default and mounts Vite as development middleware. In production it serves the compiled React application, including the SPA route fallback, from the same process.

The frontend opens directly into the Draft War Room. Use **Full console** to move into the broader Fourth Down Lab command center without losing the draft product.

## Training the empirical draft-survival model

Do not train from final-season outcomes or later ADP snapshots. The market model predicts draft behavior, so every historical row must use market information that was available before that draft.

```bash
python scripts/build_draft_survival_observations.py \
  --drafts data/raw/fantasy/historical_drafts.parquet \
  --output data/processed/draft_survival_observations.parquet

python scripts/train_draft_survival_model.py \
  --observations data/processed/draft_survival_observations.parquet \
  --output artifacts/models/draft_survival/draft_survival.joblib \
  --report artifacts/models/draft_survival/metrics.json
```

The model artifact records its training rows, independent draft count, holdout metrics, promotion result, and promotion reason. See `docs/modeling/draft_survival_training.md`.

## Evidence-aware product surfaces

- Persistent `SYNTHETIC DEMO`, `HISTORICAL BACKTEST`, `STALE`, or `LIVE` provenance
- Model version, prediction timestamp, feature cutoff, identity coverage, and missing-input warnings
- Live room state with current pick, next pick, recent picks, and positional runs
- 2-to-5-player compare tray with raw projection, VORP, roster fit, and return probability
- Server-side roster counterfactuals with projected starter slot and marginal floor / median / ceiling
- Decision-specific player rankings with overall and positional ranks, VORP, search, sorting, and CSV export
- Roster-relative waiver and legal-lineup endpoints
- League positional-needs heatmap and two-sided trade deltas
- Frozen historical prediction replay and experiment-gate results
- Lagged team-context fingerprints separated from observed standings

Gemini explains deterministic Product API results. When `GEMINI_API_KEY` is absent, the server can still route lineup, waiver, trade, draft, and ranking questions to the corresponding Product API tool and return a labeled structured fallback.

## Google AI Studio

Import the repository from GitHub into Build mode. Use:

- `ai_studio/BUILD_PROMPT.md` for the whole product;
- `ai_studio/DRAFT_WAR_ROOM_PROMPT.md` for the draft product contract.

Add `PSE_API_BASE_URL` as a server-side environment value. Keep `GEMINI_API_KEY` server-side only. See `docs/product/gemini_ai_studio.md`.

Do not ask AI Studio/Gemini to recreate Python numerical formulas in TypeScript. If a server-side draft metric is unavailable, show it as unavailable and extend the Product API rather than inventing a browser implementation.
