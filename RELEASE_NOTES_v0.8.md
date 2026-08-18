# v0.8 — Operational Draft War Room

v0.8 turns the league-aware draft engine into an operational draft-day product surface.

## Shipped

- `GET /v1/leagues/{league_id}/draft/board` for the authoritative live room board.
- `POST /v1/leagues/{league_id}/draft/compare` for 2–5 player comparisons with server-side roster counterfactuals.
- `GET /v1/draft/leagues` for Draft War Room league and roster discovery.
- React Draft War Room as the default frontend surface, while preserving the broader Fourth Down Lab console.
- Conservative polling with request cancellation, error backoff, manual refresh, and stale-data visibility.
- 2QB/superflex-aware candidate comparison that keeps raw projection, VORP/scarcity, roster fit, and pick timing separate.
- Quantile roster counterfactual simulator using legal starter assignment on every draw.
- Empirical survival-to-next-pick training pipeline with grouped draft holdout and a Brier-score promotion gate.
- Transparent normal-ADP fallback remains active unless an empirical artifact clears that gate.
- Gemini tools for live draft board retrieval and deterministic candidate comparison.

## Draft-day trust rules

The browser never computes VORP, replacement level, QB scarcity, roster marginal value, draft survival, or final draft actions. These come from Python. React only filters, sorts, renders, and selects returned rows.

The empirical draft-survival artifact is **not shipped pre-trained**. A model trained on unrelated or non-point-in-time draft data would be false precision. Build observations from archived historical drafts plus the ADP information that was available before each draft, train with `scripts/train_draft_survival_model.py`, and only promoted artifacts are used live.

## Commands

```bash
python scripts/build_draft_survival_observations.py \
  --drafts data/raw/fantasy/historical_drafts.csv

python scripts/train_draft_survival_model.py \
  --observations data/processed/draft_survival_observations.parquet

python -m player_state_engine.api

cd apps/gemini-fantasy-console
npm ci
npm run dev
```

## Validation focus

v0.8 adds regression coverage for 2QB roster marginal value, empirical-survival promotion/fallback behavior, drafted-player removal, live draft-slot resolution, and the compare API.
