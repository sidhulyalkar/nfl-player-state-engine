# Fourth Down Lab: Fantasy Modelling Workspace

A React 19 + Express 5 frontend for the NFL Player State Engine. It is designed for local development, Google AI Studio, or Cloud Run, with Python remaining authoritative for numerical model truth.

The frontend is no longer a Draft War Room with a secondary console attached. It is one persistent modelling workspace with five first-class surfaces.

## The five workspaces

### 1. Draft Room

Use this while the draft clock is running.

It answers:

- who is the best pick now;
- how much league-specific value that player adds;
- whether the player is likely to survive to the next turn;
- what value is lost by waiting;
- whether the recommendation is supported by fresh, complete inputs;
- how 2 to 5 candidates compare under roster construction and two-turn planning.

The default board stays compact. ADP, expert-rank disagreement, room rank, scoring provenance, and other audit fields remain behind progressive disclosure.

### 2. Player Intelligence

Use this when you want the full dossier for one player.

For the selected league it exposes:

- q10 / q50 / q90 projection geometry;
- replacement-point margins;
- start/sit, waiver, trade, draft, stash, and dynasty valuations;
- overall and positional ranks for every decision type;
- VORP, floor VORP, upside VORP, scarcity, and market context;
- availability and opportunity signals when present;
- raw production fields;
- frozen exact-player historical replay;
- the Player State Graph Shadow Lab when a real research artifact is mounted.

The selected player is written into the URL, so a dossier can be refreshed or shared without re-searching for the player.

Example:

```text
?workspace=intelligence&league=YOUR_LEAGUE_ID&player=CANONICAL_PLAYER_ID
```

Changing players updates the URL in place. Changing workspace surfaces creates browser history, so Back and Forward move naturally through the modelling workspace.

### 3. Portfolio

Use this before or during drafts when you want to understand exposure across all connected leagues.

It shows:

- repeated-player exposure;
- starter exposure;
- NFL-team concentration;
- positional concentration;
- which leagues contain each player;
- canonical identity quality;
- unresolved leagues that were excluded instead of guessed.

Exposure is descriptive. The product does not assume diversification is always better than concentration.

### 4. League OS

Use this for the broader season-management surface:

- trades;
- waivers;
- legal lineup optimization;
- league strength and roster needs;
- NFL state;
- detailed research views already present in the original console.

### 5. Model Observatory

Use this to decide how much confidence to place in a model layer before trusting it operationally.

It exposes:

- empirical q10-q90 coverage against the nominal 80% target;
- q50 MAE and median bias;
- mean pinball loss;
- predictive interval width;
- lower-tail and upper-tail miss rates;
- position and season calibration slices;
- artifact health;
- Player State Graph shadow replay;
- the frozen multi-season Evidence Factory;
- target-aware production champions;
- paired data availability;
- identity-permutation negative controls;
- run-wide Benjamini-Hochberg FDR q-values;
- explicit promotion blockers.

A research challenger can look interesting here without gaining production authority.

## Evidence Factory authority contract

The Evidence Factory is the frozen comparison layer behind the Observatory. It does not choose a new production model merely because one row has lower loss.

Production authority is target-aware. The default direct champion is `quantile_engine`, while carries currently resolves to `position_specific_quantile` because the production `HybridQuantileModelBundle` routes carries through position-specific heads. The historical pooled carry engine remains visible as evidence rather than being relabeled as the current champion.

For every challenger, the Evidence Factory can show:

- the target and actual production champion used for the pair;
- paired player-week count and held-out seasons;
- mean-pinball effect and paired bootstrap confidence interval;
- q50 MAE, 80% interval coverage, and interval width;
- paired data availability against evaluable outcomes;
- season, position, and week consistency;
- identity-permutation negative-control result;
- one-sided bootstrap p-value and run-wide FDR q-value;
- the exact blockers that prevent promotion.

The full run reapplies Benjamini-Hochberg correction across every challenger-vs-target-champion comparison in the run. The UI renders those server-owned q-values and does not recompute them in TypeScript.

Missing Evidence Factory artifacts return `UNAVAILABLE`. The browser does not invent placeholder benchmark results.

See `docs/modeling/evidence_factory.md` for the complete experiment contract and reproduction procedure.

## Shadow Lab authority contract

The Shadow Lab is deliberately one-way.

The target-aware direct player quantile stack remains production-authoritative. The Player State Graph is a research challenger until frozen replay earns promotion.

The Shadow Lab may show:

- direct-vs-graph q10 / q50 / q90 disagreement;
- interval overlap;
- role-state and regime context;
- teammate target/carry allocation;
- explicit residual opportunity for unmodeled teammates;
- bounded role, team-volume, and availability sensitivity controls.

It may not silently alter:

- production projections;
- production ranks;
- draft actions;
- lineup recommendations;
- waiver or trade valuations.

Scenario controls are labeled sensitivity analysis, not calibrated forecasts.

## Scoring comparability

A graph artifact is not assumed to be comparable to the active league merely because both are called PPR.

Research runs write a `run_manifest.json` with their scoring contract. Direct-vs-graph comparison is marked decision-comparable only when the relevant scoring contract matches, including tight-end reception premium.

If the manifest is missing, legacy, or mismatched, raw research output can remain visible but decision comparability fails closed.

## Live league discovery

The product can read league snapshots from both:

```text
data/product/leagues
data/product/live_leagues
```

The live portfolio sync may name a file by connection key rather than by league ID. The Product API therefore resolves snapshots by the league identity embedded inside the JSON instead of assuming filename equals league ID.

This same discovery behavior backs Player Intelligence and Portfolio, so a live-only Sleeper or ESPN snapshot can appear in the selector without first being copied into the primary store.

Ambiguous multi-roster snapshots are excluded from cross-league exposure unless the user's roster can be resolved from imported identity or explicit snapshot metadata.

## Primary Product API surfaces

```text
GET  /v1/draft/leagues
GET  /v1/leagues/{league_id}/draft/board
GET  /v1/leagues/{league_id}/draft/reliable-board
POST /v1/leagues/{league_id}/draft/compare
POST /v1/leagues/{league_id}/draft/plan

GET  /v1/intelligence/leagues
GET  /v1/intelligence/leagues/{league_id}/players
GET  /v1/leagues/{league_id}/players/{player_id}/intelligence
GET  /v1/leagues/{league_id}/players/{player_id}/shadow
POST /v1/leagues/{league_id}/players/{player_id}/scenario

GET  /v1/portfolio/exposure

GET  /v1/research/diagnostics
GET  /v1/research/players/{player_id}/history
GET  /v1/model/shadow-evaluation
GET  /v1/model/evidence-factory
GET  /v1/model/evidence-factory?target=fantasy_points_ppr
GET  /v1/model/observatory
```

The browser renders server-returned calculations. Missing model metrics should remain unavailable until the Python Product API provides them.

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

Express listens on `0.0.0.0:3000` by default and mounts Vite as development middleware. In production it serves the compiled React application, including the SPA fallback, from the same process.

Open the root URL for Draft Room, or deep-link to a workspace with:

```text
?workspace=draft
?workspace=intelligence
?workspace=portfolio
?workspace=league
?workspace=model
```

## Live league configuration

Use the portfolio configuration template:

```text
configs/fantasy/leagues.example.yaml
```

The repository already includes format profiles for:

```text
configs/fantasy/12_team_half_ppr_median.yaml
configs/fantasy/12_team_half_ppr_median_2qb.yaml
configs/fantasy/8_team_ppr_2qb_expanded.yaml
```

Profiles are pre-draft fallbacks. When Sleeper or ESPN supplies live roster positions and scoring settings, `league_config_from_snapshot()` treats the platform snapshot as authoritative for supported rules.

Unsupported scoring keys remain visible in provenance rather than being silently approximated as exact.

## Player State Graph research run

Run the graph as a research artifact generator:

```bash
python scripts/run_player_state_graph_research.py \
  --history path/to/point_in_time_history.parquet \
  --forecast-rows path/to/frozen_forecast_rows.parquet \
  --league-config configs/fantasy/8_team_ppr_2qb_expanded.yaml \
  --output-dir artifacts/player_state_graph
```

Important outputs include:

```text
player_state_graph_summaries.parquet
dynamic_role_states.parquet
coherent_scored_draws.parquet
player_intelligence_cards.json
run_manifest.json
report.md
```

The UI does not fabricate a graph forecast if these artifacts are unavailable.

## Evidence Factory run

Build the canonical frozen evidence ledger from the stored historical benchmark and optional graph artifacts:

```bash
python scripts/run_evidence_factory.py \
  --benchmark-root artifacts/reports/benchmark_real \
  --graph-root artifacts/player_state_graph \
  --output-dir artifacts/evidence_factory
```

The output bundle includes canonical predictions, method and slice metrics, paired comparisons, the experiment ledger, identity-permutation controls, a SHA-256 provenance manifest, and a Markdown report. Carries resolves to the position-specific production head by default.

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

External rankings and ADP are audit/challenger evidence. They do not numerically overwrite the production projection model.

## Ranking validation

```bash
python scripts/build_format_ranking_benchmark.py \
  --projections artifacts/predictions/product_player_values.csv \
  --rankings-root data/external/rankings
```

The benchmark checks 1QB/2QB/superflex, team count, scoring, TE premium, expanded lineups, scoring exactness, external agreement, and structural monotonicity. Historical roster-utility replay remains required for promotion.

## Training the empirical draft-survival model

Every historical row must use market information that was available before that draft.

```bash
python scripts/build_draft_survival_observations.py \
  --drafts data/raw/fantasy/historical_drafts.parquet \
  --output data/processed/draft_survival_observations.parquet

python scripts/train_draft_survival_model.py \
  --observations data/processed/draft_survival_observations.parquet \
  --output artifacts/models/draft_survival/draft_survival.joblib \
  --report artifacts/models/draft_survival/metrics.json
```

## Gemini responsibilities

- React renders server-owned state, comparisons, evidence, and provenance.
- The Node server keeps `GEMINI_API_KEY` private and proxies the Python Product API.
- Gemini performs tool selection, comparison, and explanation only.
- Python remains authoritative for projections, exact league scoring, starter allocation, VORP, scarcity, draft survival, roster utility, simulation, evidence statistics, and production actions.
- The deterministic product remains usable if Gemini is disabled.

Do not recreate missing Python numerical formulas in TypeScript. Extend the Product API instead.

## Further reading

```text
docs/product/modelling_workspace.md
docs/product/gemini_ai_studio.md
docs/modeling/evidence_factory.md
docs/modeling/player_state_graph_v2.md
docs/modeling/ranking_calibration_v09.md
docs/data/ranking_and_news_sources.md
```
