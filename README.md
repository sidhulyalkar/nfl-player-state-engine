# NFL Player State Engine v0.17

**Fourth Down Lab** is a leakage-safe NFL intelligence, fantasy valuation, draft-decision, game-simulation, and continual-learning system.

The v0.17 release is organized around one practical rule: **the interface may explain more than the model, but it may never claim more authority than the evidence earned.** Numerical truth stays in Python, model promotion fails closed, and missing data remains unavailable instead of being filled with plausible-looking placeholders.

> Research and entertainment only. The project does not place wagers or promise profit.

## Start here for a draft

If you are downloading the repository to use or redesign the product, read **[`DRAFT_DAY.md`](DRAFT_DAY.md)** first.

Fresh checkout:

```bash
python -m pip install -e ".[dev,api,intelligence,espn]"
cd apps/gemini-fantasy-console
npm ci
cd ../..
python scripts/check_draft_checkout.py
```

Run locally in two terminals:

```bash
# Terminal 1
python -m player_state_engine.api

# Terminal 2
cd apps/gemini-fantasy-console
npm run dev
```

Then open `http://localhost:3000`.

Before using the board for a real draft, run the strict data-plane check:

```bash
python scripts/check_draft_checkout.py --strict-data
```

A green frontend build is not a release verdict. Production projections, current NFL state, special-teams fallback evidence, and league snapshots must also exist and pass their own authority/freshness checks.

## The product

The React 19 + Express 5 workspace lives in `apps/gemini-fantasy-console` and exposes five first-class surfaces:

1. **Draft Room** — best-pick-now guidance, league-specific value, room survival, wait cost, roster fit, candidate comparison, and qualification state.
2. **Player Intelligence** — league-aware player dossiers, projection geometry, replacement economics, market context, historical replay, and research-only shadow analysis.
3. **NFL Hub / League OS** — current roster/depth/schedule truth, source health, roster movement, lineups, waivers, trades, and league state.
4. **Portfolio** — cross-league player, team, starter, and position exposure with canonical identity diagnostics.
5. **Model Observatory** — calibration, drift, evidence artifacts, challenger evaluation, provenance, and explicit promotion blockers.

Useful deep links:

```text
?workspace=draft
?workspace=intelligence&league=LEAGUE_ID&player=CANONICAL_PLAYER_ID
?workspace=portfolio
?workspace=league
?workspace=model
```

The browser does not own fantasy math. Python owns projections, scoring, replacement levels, VORP, scarcity, simulation, evidence statistics, qualification, and release gates. TypeScript renders those results and their provenance.

## Draft authority map

The repository deliberately separates several kinds of authority that are easy to conflate:

| Lane | Authority rule |
| --- | --- |
| Skill-player projections | Must come from an immutable, explicitly approved projection bundle before production use. |
| League scoring | Every league resolves by its exact scoring-contract fingerprint; no PPR/half-PPR substitution is allowed. |
| Decision tails | `q50_only` means q10/q90 may remain visible for audit but cannot affect the draft decision. |
| Median-game scoring | Separate team-week policy. It is not made exact by a player-season floor heuristic. |
| Kicker / DST | Separate `external_market_only` late-round lane unless a specialist model is independently qualified. |
| NFL Hub | Observational current-state authority only; roster/news context cannot silently overwrite a production projection. |
| Gemini copilot | Explanation and tool orchestration only. It is never the numerical control plane. |

The multicontract release gate produces **READY**, **PROVISIONAL**, or **BLOCKED**. PROVISIONAL is intentionally narrow and cannot upgrade model authority.

## Gemini is optional

The Node server keeps `GEMINI_API_KEY` private. The default configured model is `gemini-3.7-flash`.

If no Gemini key is present, the copilot falls back to deterministic Product API tools for draft, lineup, waiver, trade, and ranking questions. The core product therefore remains usable when the language-model layer is disabled or unavailable.

For a frontend implementation or redesign, preserve the contract in [`DRAFT_DAY.md`](DRAFT_DAY.md): do not recreate Python formulas in TypeScript, do not invent unavailable model values, and keep authority/freshness/scoring provenance visible.

## Current NFL state

Refresh the maintained observational hub with:

```bash
python scripts/refresh_nfl_hub.py --season 2026
```

Refresh the model-free K/DST market lane with:

```bash
python scripts/refresh_special_teams_market.py --season 2026
```

These are separate from projection promotion. A fresh NFL Hub snapshot does not make an unapproved model production-ready, and a projection bundle does not make stale roster state acceptable.

## Fantasy league profiles

The repository includes reusable profiles under `configs/fantasy/`, including expanded multi-QB and median-scoring formats. Live Sleeper/ESPN snapshots are authoritative for supported platform settings when imported.

Scoring-contract identity intentionally excludes roster size, flex structure, risk preference, replacement settings, and draft type. Those affect downstream valuation and strategy, not the underlying player fantasy-point scoring operation.

## Evidence-first modelling

New methods do not gain authority because they are sophisticated. Promotion requires timestamp-safe comparisons, calibration checks, negative controls where appropriate, and downstream evidence.

The repository contains:

- expanding-window weekly projection benchmarks;
- position-specific calibration and carry handling;
- immutable artifact registry and manual champion promotion;
- frozen Evidence Factory comparisons with paired bootstrap effects and FDR control;
- draft decision audit capture;
- candidate-scoped draft actionability diagnostics;
- historical/current availability research, including preserved negative experiments;
- counterfactual draft-replay research;
- a play-by-play football world-model laboratory through the v0.16 terminal-family stack.

Research challengers remain visible without silently becoming production methods.

## Repository map

```text
apps/gemini-fantasy-console/   React + Express modelling workspace
configs/fantasy/              League/scoring profiles
src/player_state_engine/api/  Product and research API
src/player_state_engine/fantasy/
                              Scoring, valuation, draft logic, preseason contracts
src/player_state_engine/product/
                              NFL Hub, artifacts, release/readiness surfaces
src/player_state_engine/evaluation/
                              Frozen benchmark/evidence machinery
src/player_state_engine/game_intelligence/
                              Generative football research stack
scripts/                      Operators, refreshes, benchmarks, release checks
docs/                         Detailed product, modelling, data, and release contracts
```

## Validation

The ordinary CI suite runs:

- Ruff over package/tests and operational research code;
- Python compilation;
- the complete Python test suite;
- frozen evidence and structured-intelligence smoke contracts;
- the frontend production build.

The dedicated draft-checkout workflow additionally recreates the intended local environment with Python 3.12 and Node 22, checks the v0.17 package/API identity, runs the checkout preflight, and builds the React + Express workspace from the lockfile.

Local checks:

```bash
pytest
cd apps/gemini-fantasy-console && npm run build && cd ../..
python scripts/check_draft_checkout.py
```

For actual draft use, add the strict data-plane and multicontract release checks described in [`DRAFT_DAY.md`](DRAFT_DAY.md).

## Deeper documentation

- [`DRAFT_DAY.md`](DRAFT_DAY.md) — operational release and Gemini handoff contract
- [`apps/gemini-fantasy-console/README.md`](apps/gemini-fantasy-console/README.md) — workspace/API details
- [`docs/product/modelling_workspace.md`](docs/product/modelling_workspace.md) — product architecture
- [`docs/product/draft_actionability.md`](docs/product/draft_actionability.md) — current-pick comparability vs global league readiness
- [`docs/modeling/immutable_production_artifacts.md`](docs/modeling/immutable_production_artifacts.md) — content-addressed model authority
- [`docs/modeling/evidence_factory.md`](docs/modeling/evidence_factory.md) — frozen comparison contract
- [`docs/modeling/terminal_family_v016.md`](docs/modeling/terminal_family_v016.md) — v0.16 generative research
- [`docs/releases/v0.16.md`](docs/releases/v0.16.md) — previous release history
