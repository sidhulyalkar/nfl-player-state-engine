# Google AI Studio implementation guide

## Recommended role

Use Google AI Studio Build mode to iterate on the existing React + Node application in `apps/gemini-fantasy-console`. Keep the Python Player State Engine as the authoritative numerical service.

The frontend is already a five-surface modelling workspace. Do not treat the older Draft War Room milestone documents as instructions to replace or rebuild the current shell.

The current product surfaces are:

1. Draft Room
2. Player Intelligence
3. Portfolio
4. League OS
5. Model Observatory

Read `apps/gemini-fantasy-console/README.md` and `docs/product/modelling_workspace.md` before changing the frontend.

As of 2026, Google AI Studio Build mode supports importing a GitHub project, a React-oriented full-stack web runtime, server-side Node code, server-side secrets, npm packages, and Cloud Run deployment. Use those capabilities to improve the product shell and Gemini tool-routing layer around the Python API.

Current Google documentation:

- Build mode: https://ai.google.dev/gemini-api/docs/aistudio-build-mode
- Function calling: https://ai.google.dev/gemini-api/docs/function-calling
- Structured output: https://ai.google.dev/gemini-api/docs/structured-output
- Fine-tuning status: https://ai.google.dev/gemini-api/docs/model-tuning

## Important model boundary

Do **not** treat Gemini as the fantasy prediction model.

The custom trained and deterministic models live in the Python engine, including:

- player availability and participation;
- position-specific opportunity;
- conditional efficiency;
- weekly and season fantasy distributions;
- QB starter-security;
- draft-market survival;
- roster marginal-value simulation;
- exact supported league rescoring;
- Player State Graph research simulation and promotion evidence.

Gemini should consume those outputs through typed tools and explain them. The numerical models can then be backtested, calibrated, versioned, and promoted independently.

The Player State Graph remains a research challenger unless frozen replay clears the promotion policy. A sophisticated Gemini explanation must never imply otherwise.

## Setup

1. Push or sync this repository to GitHub.
2. Open Google AI Studio Build mode.
3. Import the GitHub repository.
4. Point the agent to `apps/gemini-fantasy-console`.
5. Read `apps/gemini-fantasy-console/README.md`.
6. Read `docs/product/modelling_workspace.md`.
7. Use `ai_studio/BUILD_PROMPT.md` as background product context, not as permission to discard newer implementation.
8. Treat `ai_studio/DRAFT_WAR_ROOM_PROMPT.md` as historical design context for the Draft Room surface.
9. Add `PSE_API_BASE_URL` as a server-side secret / environment value.
10. Keep `GEMINI_API_KEY` server-side only.
11. Never put ESPN `SWID` or `espn_s2` credentials in client code.
12. Run the application and verify `/api/health` plus the PSE `/health` endpoint.
13. Validate the deterministic product with Gemini disabled.
14. Deploy to Cloud Run only after provenance, stale-data, missing-artifact, and error states have been tested.

## Existing workspace contract

### Draft Room

The Draft Room already provides live multi-league decision support with:

- league-specific projections and VORP;
- roster construction;
- pick timing;
- return probability;
- wait loss;
- guarded reliability;
- external-ranking audit context;
- 2-to-5-player comparison;
- research two-turn planning.

Do not replace the server-owned draft score with a Gemini-generated ranking.

### Player Intelligence

Player Intelligence already exposes:

- complete player search across connected leagues;
- shareable league/player deep links;
- six decision-specific valuations;
- projection geometry;
- raw model fields;
- signal visualization;
- exact-player frozen history;
- Player State Graph Shadow Lab.

A URL such as the following is navigation state only:

```text
?workspace=intelligence&league=LEAGUE_ID&player=CANONICAL_PLAYER_ID
```

Do not use URL values to override model output.

### Portfolio

Portfolio exposes cross-league roster concentration. It uses canonical identities where available and excludes unresolved user rosters rather than guessing.

Do not turn exposure into an automatic diversification penalty unless a separately validated decision model earns that behavior.

### League OS

League OS contains the broader trade, waiver, lineup, league-state, NFL-state, and detailed research surfaces.

### Model Observatory

Model Observatory exposes calibration, sharpness, drift, artifact health, Player State Graph shadow replay, and promotion blockers.

It is an evidence surface, not a control that can promote a challenger by UI interaction.

## Gemini responsibilities

Gemini may:

- translate natural-language questions into typed tool calls;
- compare Product API results;
- explain model uncertainty and reason codes;
- construct sequences of league queries;
- compare draft candidates across several dimensions;
- summarize trade and waiver alternatives;
- explain direct-vs-graph disagreement;
- summarize portfolio exposure;
- explain historical calibration and promotion blockers;
- generate user-facing narratives and follow-up questions;
- use structured output to return stable comparison objects.

Gemini may not:

- invent projections or ownership;
- invent live draft picks;
- invent injuries, ADP, or news;
- replace deterministic lineup optimization;
- calculate VORP or replacement levels itself;
- calculate trade values outside the Product API;
- silently take transactions on a fantasy platform;
- claim that a custom trained model exists when no model artifact exists;
- use one-QB rankings as a hidden proxy for 2QB value;
- convert Shadow Lab sensitivity output into a production forecast;
- promote the Player State Graph based on narrative plausibility;
- hide scoring-contract mismatch between production and research artifacts.

## Tool design

The Node server should remain a thin Gemini/tool boundary over the Product API.

Useful deterministic tool concepts include:

- `get_league_context`
- `get_player_board`
- `get_live_draft_board`
- `compare_draft_candidates`
- `get_player_intelligence`
- `get_player_shadow`
- `run_player_sensitivity`
- `get_portfolio_exposure`
- `get_trade_suggestions`
- `get_waiver_board`
- `get_optimized_lineup`
- `get_model_observatory`

Function tools should be small, typed, read-only by default, and deterministic. The model chooses the tool; the application executes it; Gemini explains the returned result.

Use structured outputs when the React client needs stable fields such as:

```text
recommendation
best_raw_projection
best_league_value
best_roster_fit
best_pick_now
assumptions
uncertainties
production_authority
research_disagreement
supporting_tool_results
```

## Source-of-truth hierarchy

Use this hierarchy whenever data conflicts:

1. current live platform snapshot for league rules, ownership, roster identity, and completed picks;
2. current versioned Python production prediction artifact;
3. deterministic league-value / draft calculations;
4. timestamped market ADP and external ranking audit context;
5. validated intelligence evidence;
6. research challenger output with explicit authority label;
7. Gemini explanation.

Gemini never overrides higher layers with a plausible narrative.

## Live-store discovery

The operational product can read league snapshots from both:

```text
data/product/leagues
data/product/live_leagues
```

Live sync files may be named by connection key rather than platform league ID. Product API routes resolve the embedded league identity instead of relying on filename equality.

Do not reintroduce frontend-only assumptions about snapshot file names.

## Freshness handling

The UI must expose both platform freshness and model freshness.

Recommended states include:

- `LIVE`: recent platform snapshot and valid projection artifact;
- `STALE`: last valid data retained, refresh overdue or enrichment failed;
- `HISTORICAL`: intentionally replaying a past snapshot;
- `SYNTHETIC DEMO`: development fixture only;
- `UNAVAILABLE`: no trustworthy projection / league / research artifact exists.

Do not replace stale live data with demo values.

## Research and Shadow Lab handling

The browser must fail closed when research artifacts are absent.

Do not recreate Player State Graph outputs in TypeScript.

Direct-vs-graph decision comparability requires a compatible research run manifest. Base scoring weights and tight-end premium are part of the comparability contract.

Scenario controls represent bounded sensitivity analysis. They are not calibrated forecast controls and may not mutate production rankings or actions.

## Prompt evaluation

Maintain a regression set containing:

- ambiguous player names;
- two leagues with different scoring;
- the same player compared in 8-team and 12-team multi-QB formats;
- missing projections;
- missing ADP;
- stale platform snapshot;
- a positional run before the user's next pick;
- a player with strong raw projection but weak roster fit;
- a player with lower raw projection but severe positional scarcity;
- a player deep-link that does not exist in the selected league;
- a live-only league snapshot stored under a connection-key filename;
- a graph artifact scored under the wrong league contract;
- a TE-premium mismatch with otherwise identical PPR weights;
- a missing graph artifact;
- a graph challenger with a better headline metric but uncleared promotion blockers;
- a request to turn research sensitivity into a production recommendation;
- a request for a trade that harms the other manager;
- requests to invent certainty;
- multi-step queries such as “compare these three players, tell me who I can wait on, then explain the graph disagreement for the top two.”

Score separately:

- tool selection correctness;
- argument correctness;
- factual grounding;
- agreement with deterministic ranking fields;
- production/research authority preservation;
- uncertainty language;
- source/provenance visibility;
- usefulness under a live draft clock.

## AI Studio iteration workflow

For each AI Studio iteration:

1. inspect the current implementation before editing;
2. read the modelling workspace operator guide;
3. make one coherent product change at a time;
4. preserve the Python calculation boundary;
5. preserve production-vs-research authority labels;
6. run the frontend production build;
7. test missing/stale API states;
8. test deep links and browser Back/Forward behavior when navigation changes;
9. test Gemini-off fallback behavior;
10. inspect diffs before syncing changes back to GitHub.

The product should become easier to interrogate without allowing the language model to become an unvalidated numerical oracle.
