# Draft-day checkout guide

This is the operational entry point for the Sept. 1 fantasy draft release. It separates **software/build readiness** from **real draft-data readiness** so a fresh checkout cannot look healthy merely because the React application renders.

## Authority map

The UI must preserve these boundaries:

| Lane | Current authority |
| --- | --- |
| NFL roster/depth/schedule state | observational NFL Hub only |
| PPR season-score center and tails | direct preseason league-score model; tails require qualified calibration |
| half-PPR season-score center | direct preseason league-score model |
| half-PPR q10/q90 decision tails | not qualified; use `q50_only` decision policy |
| median-game adjustment | not qualified; core half-PPR board may be PROVISIONAL, never READY because of median policy |
| kicker / DST | fresh `external_market_only` ordering, never model q50/VORP |
| Gemini copilot | explanation/tool orchestration only; never numerical authority |

`READY`, `PROVISIONAL`, and `BLOCKED` are release-gate outputs, not visual styling choices.

## Requirements

- Python 3.11+
- Node.js 22+
- npm
- internet access for current nflverse / league refresh operations
- optional Gemini API key for the copilot only

The deterministic draft product works without `GEMINI_API_KEY`.

## Fresh checkout

From the repository root:

```bash
python -m pip install -e ".[dev,api,intelligence,espn]"
cd apps/gemini-fantasy-console
npm ci
cd ../..
```

Copy the root `.env.example` to `.env` and `apps/gemini-fantasy-console/.env.example` to `apps/gemini-fantasy-console/.env` if you want local overrides. Do not commit populated credentials.

Then run the build preflight:

```bash
python scripts/check_draft_checkout.py
```

or, on systems with `make`:

```bash
make draft-install
make draft-preflight
```

A fresh source checkout should clear the **build** layer even when production draft artifacts have not yet been materialized.

## Build the full frontend

```bash
cd apps/gemini-fantasy-console
npm run build
```

The production build compiles both the React/Vite client and the TypeScript Express server. CI runs this build on every qualifying PR.

## Run locally

Terminal 1, repository root:

```bash
python -m player_state_engine.api
```

The Product API listens on `http://localhost:8000`.

Terminal 2:

```bash
cd apps/gemini-fantasy-console
npm run dev
```

The modelling workspace listens on `http://localhost:3000` and proxies deterministic Product API calls to port 8000.

Useful deep links:

```text
http://localhost:3000/?workspace=draft
http://localhost:3000/?workspace=intelligence
http://localhost:3000/?workspace=portfolio
http://localhost:3000/?workspace=league
http://localhost:3000/?workspace=model
```

## Production projection shape

`artifacts/predictions/product_player_values.csv` is one configured product artifact, but it may contain several exact fantasy scoring contracts. Its production shape is long-form:

```text
(scoring_contract_id, player_id) -> one row
```

The same player can therefore appear once for PPR and once for half-PPR. That is intentional. Python selects the current league's exact `LeagueConfig.scoring_contract_id` **before** identity checks, scoring, replacement levels, VORP, scarcity, candidate actionability, room simulation, or decision scoring.

Within one scoring contract, duplicate `player_id` rows are an error. If a live league requests a scoring-contract fingerprint that the artifact does not contain, serving fails closed rather than borrowing another league's values.

The current decision-tail authority is also contract-specific:

- PPR: `qualified_distribution`; qualified q10/q50/q90 may affect season decisions.
- half-PPR: `q50_only`; q10/q90 may remain visible for audit, but they cannot affect draft, trade, stash, dynasty, reliability, or season-uncertainty reasoning.

Weekly start/sit uncertainty is a separate weekly forecasting authority lane and must not be inferred from the preseason season-distribution policy.

## NFL Hub separation

NFL Hub is observational and league-independent. It must not arbitrarily choose one fantasy scoring contract from the multicontract draft artifact.

By default:

```text
PSE_NFL_HUB_PROJECTIONS_PATH=
```

so the Hub refreshes from roster, depth-chart, injury, ranking, identity, and schedule sources without a fantasy projection overlay. If a deliberately single-contract, read-only projection context is useful for an experiment, it may be configured separately. Never point NFL Hub at the multicontract production draft artifact merely to populate UI fields.

## Real draft-data preflight

Before using the board for an actual draft, all of these must exist and be current:

```text
artifacts/predictions/product_player_values.csv
data/product/nfl_hub/current.json
data/product/special_teams_market/current.json
data/product/leagues/*.json or data/product/live_leagues/*.json
```

Run:

```bash
python scripts/check_draft_checkout.py --strict-data
```

A missing artifact is a blocker, not an invitation to create placeholder values.

Refresh maintained current-state sources with:

```bash
python scripts/refresh_nfl_hub.py --season 2026
python scripts/refresh_special_teams_market.py --season 2026
```

The projection artifact must come from the immutable preseason release pipeline and its exact scoring-contract authority. Do not manually edit `product_player_values.csv` to make the UI green.

## Gemini frontend handoff contract

When asking Gemini or another coding agent to redesign/finish the frontend, give it this repository root and these constraints:

1. Treat the Python Product API as the only numerical authority.
2. Do not reimplement scoring, scoring-contract selection, VORP, replacement levels, scarcity, calibration, survival probability, simulation, or release gates in TypeScript.
3. Do not invent placeholder projections, ADP, injuries, league state, model metrics, or player identities when an endpoint returns unavailable.
4. Preserve `decision_quantile_policy`: `q50_only` means q10/q90 cannot influence season decisions, including indirect reliability or uncertainty signals.
5. Preserve `league_scoring_exact`, `scoring_contract_id`, artifact authority, freshness, and release status visibly in the UI.
6. Never merge or deduplicate product rows in the browser by `player_id` before the backend has selected the league scoring contract. The API should return the already-selected league view.
7. Median scoring is a separate team-week policy. Do not revive the retired floor-VORP heuristic.
8. K/DST remain visually and semantically separate `external_market_only` late-round guidance.
9. Keep the NFL Hub observational. News/depth/roster movement can explain a recommendation but cannot silently overwrite the production model or select a fantasy scoring contract.
10. Keep the app useful with Gemini disabled. Copilot is an enhancement, not the control plane.
11. Run `npm run build` before proposing completion.

The design target is a calm NFL command center: Draft Room first, Player Intelligence second, NFL Hub/context always reachable, and research/provenance available without drowning the pick clock in diagnostics.

## Release checks

Before declaring the checkout draft-ready:

```bash
pytest
cd apps/gemini-fantasy-console && npm run build && cd ../..
python scripts/check_draft_checkout.py --strict-data
```

Then run the multicontract Sept. 1 release gate against the immutable production bundle and current snapshots. A green build does not override a `BLOCKED` release verdict.
