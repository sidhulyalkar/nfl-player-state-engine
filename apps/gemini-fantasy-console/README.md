# Fourth Down Lab: Gemini Fantasy Console

A React 19 + Express 5 full-stack frontend for the NFL Player State Engine. It is designed for Google AI Studio, local development, or Cloud Run.

## v0.9 Draft War Room

The **Draft War Room** is the primary frontend surface. It is a live multi-league workspace for comparing 2 to 5 available players under the exact roster construction, scoring rules, current roster, replacement economy, market timing, and evidence state of the active draft.

The browser consumes authoritative Python endpoints:

```text
GET  /v1/draft/leagues
GET  /v1/leagues/{league_id}/draft/board
POST /v1/leagues/{league_id}/draft/compare
POST /v1/leagues/{league_id}/draft/plan
GET  /v1/rankings/sources
GET  /v1/leagues/{league_id}/rankings/audit
```

The War Room keeps these concepts separate:

- football outcome projection;
- league-specific value and replacement economics;
- current-roster marginal value;
- draft-room timing and survival to the next pick;
- external expert/market disagreement;
- research-only multi-pick lookahead.

This separation is essential in 2QB, superflex, unusual roster-depth, TE-premium, and custom-scoring formats.

## What v0.9 adds to the interface

### Scoring provenance

League scoring is no longer assumed to be exact merely because a league was imported.

The UI can show whether a player is using:

```text
correlated/provided league quantiles
component-quantile league rescore
generic fantasy-point fallback
```

If unsupported live scoring rules or missing component projections prevent exact rescoring, the War Room displays the limitation instead of hiding it.

### Dynamic scarcity and wait loss

The production live draft score remains authoritative. A separately labeled challenger exposes:

- remaining positive-VORP supply;
- expected same-position picks before the user's next turn;
- expected positional supply at the next turn;
- probability-weighted value of likely surviving alternatives;
- positional value lost by waiting;
- challenger rank and delta.

The challenger does not change `draft_action` unless historical replay earns promotion.

### Ranking calibration

External rankings and ADP are shown as **audit context**, never as the numerical source of truth.

The UI may display:

- external consensus rank;
- expert rank dispersion;
- source count;
- model-versus-external rank delta;
- cross-market ADP and dispersion.

A large disagreement is a reason to investigate, not an instruction to average the model toward consensus.

### Research two-turn lookahead

The comparison tray can request `POST /draft/plan`, which estimates the current candidate plus the best value likely to survive until the next manager pick.

The UI must visibly label this result **UNPROMOTED / RESEARCH**. It cannot replace the production best-pick-now recommendation until frozen historical room-state replay shows improved utility.

## Live behavior

While a draft is active, React conservatively polls the Product API and cancels obsolete requests. New completed picks are canonicalized, removed from the available board, and trigger fresh league value, roster need, tier cliff, survival, and wait-loss calculations. Manual force refresh is always available.

The UI preserves the last valid board when a platform refresh fails and shows freshness or stale-state warnings instead of fabricating replacement data. Sleeper refreshes reuse the server-side player-map cache; ESPN is polled more conservatively.

Draft survival uses the transparent normal-ADP approximation unless a trained empirical artifact clears its grouped-holdout Brier promotion gate.

## Responsibilities

- React renders server-returned state, comparisons, evidence, and provenance.
- The Node server keeps `GEMINI_API_KEY` private and proxies the Python Product API.
- Gemini performs tool selection, comparison, and explanation only.
- Python remains authoritative for projections, exact league scoring, starter allocation, VORP, scarcity, draft survival, roster utility, simulation, and production draft actions.
- External rankings are challenger/audit evidence only.
- The deterministic product remains usable if Gemini is disabled.

## Local start

```bash
# Terminal 1, repository root
python -m pip install -e ".[api,intelligence,espn]"
python -m player_state_engine.api

# Terminal 2
cd apps/gemini-fantasy-console
npm ci
cp .env.example .env
npm run dev
```

Express listens on `0.0.0.0:3000` by default and mounts Vite as development middleware. In production it serves the compiled React application, including the SPA route fallback, from the same process.

The frontend opens directly into the Draft War Room. Use **Full console** to move into the broader Fourth Down Lab command center.

## Ranking source ingestion

Official FantasyPros snapshots can be archived when `PSE_FANTASYPROS_API_KEY` is configured:

```bash
python scripts/fetch_fantasypros_rankings.py \
  --season 2026 \
  --position ALL \
  --scoring HALF \
  --teams 12 \
  --qb-format 2qb
```

Licensed or user-provided exports from other sources can be normalized without adding page scrapers:

```bash
python scripts/normalize_ranking_export.py \
  --input rankings.csv \
  --source fantasy_life \
  --source-kind expert \
  --ranking-type draft \
  --scoring ppr \
  --teams 8 \
  --qb-format 2qb \
  --output data/external/rankings/fantasy_life/20260818T030000Z.parquet
```

See `docs/data/ranking_and_news_sources.md`.

## Ranking validation

Use the format matrix before promoting a ranking challenger:

```bash
python scripts/build_format_ranking_benchmark.py \
  --projections artifacts/predictions/product_player_values.csv \
  --rankings-root data/external/rankings
```

The benchmark checks 1QB/2QB/superflex, team count, scoring, TE premium, expanded lineups, scoring exactness, external agreement, and structural monotonicity. Historical roster-utility replay is required by default for promotion.

See `docs/modeling/ranking_calibration_v09.md`.

## Training the empirical draft-survival model

Do not train from final-season outcomes or later ADP snapshots. Every historical row must use market information that was available before that draft.

```bash
python scripts/build_draft_survival_observations.py \
  --drafts data/raw/fantasy/historical_drafts.parquet \
  --output data/processed/draft_survival_observations.parquet

python scripts/train_draft_survival_model.py \
  --observations data/processed/draft_survival_observations.parquet \
  --output artifacts/models/draft_survival/draft_survival.joblib \
  --report artifacts/models/draft_survival/metrics.json
```

## Evidence-aware product surfaces

- `LIVE`, `STALE`, `HISTORICAL BACKTEST`, and `SYNTHETIC DEMO` provenance
- model version, projection freshness, source cutoff, and missing inputs
- scoring exactness and unsupported live-rule warnings
- live room state, current pick, next pick, recent picks, and positional runs
- 2-to-5-player comparison with raw projection, VORP, roster fit, timing, calibration, and research lookahead
- server-side roster counterfactuals and legal lineup optimization
- dynamic wait-loss and positional supply diagnostics
- expert/market disagreement without consensus leakage into production
- frozen historical policy replay and promotion gates

Gemini explains deterministic Product API results. When `GEMINI_API_KEY` is absent, deterministic draft, lineup, waiver, trade, and ranking-calibration features remain usable.

## Google AI Studio

Import the repository into Build mode and read:

```text
ai_studio/BUILD_PROMPT.md
ai_studio/DRAFT_WAR_ROOM_PROMPT.md
docs/product/gemini_ai_studio.md
docs/modeling/ranking_calibration_v09.md
docs/data/ranking_and_news_sources.md
```

Add `PSE_API_BASE_URL` as a server-side environment value. Keep `GEMINI_API_KEY`, ESPN session credentials, and ranking-provider API credentials server-side only.

Do not ask AI Studio or Gemini to recreate Python numerical formulas in TypeScript. If a server-side metric is unavailable, show it as unavailable and extend the Product API instead of inventing a browser implementation.
