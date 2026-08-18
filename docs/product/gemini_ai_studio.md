# Google AI Studio implementation guide

## Recommended role

Use Google AI Studio Build mode to iterate on the existing React + Node application in `apps/gemini-fantasy-console`. Keep the Python Player State Engine as the authoritative numerical service.

As of 2026, Google AI Studio Build mode supports importing a GitHub project, a React-oriented full-stack web runtime, server-side Node code, server-side secrets, npm packages, and Cloud Run deployment. Use those capabilities to build the product shell and Gemini tool-routing layer around the Python API.

Current Google documentation:

- Build mode: https://ai.google.dev/gemini-api/docs/aistudio-build-mode
- Function calling: https://ai.google.dev/gemini-api/docs/function-calling
- Structured output: https://ai.google.dev/gemini-api/docs/structured-output
- Fine-tuning status: https://ai.google.dev/gemini-api/docs/model-tuning

## Important model boundary

Do **not** treat Gemini as the fantasy prediction model.

Google currently states that fine-tuning is not available through the Gemini API or AI Studio. The custom trained models for this project therefore live in the Python engine:

- player availability and participation;
- position-specific opportunity;
- conditional efficiency;
- weekly and season fantasy distributions;
- QB starter-security;
- draft-market survival;
- roster marginal-value simulation.

Gemini should consume those model outputs through typed tools and explain them. This is a stronger architecture anyway because the numerical models can be backtested, calibrated, versioned, and promoted independently.

See `docs/modeling/draft_intelligence_models.md`.

## Setup

1. Push or sync this repository to GitHub.
2. Open Google AI Studio Build mode.
3. Import the GitHub repository.
4. Point the agent to `apps/gemini-fantasy-console`.
5. Use `ai_studio/BUILD_PROMPT.md` for the overall product.
6. Use `ai_studio/DRAFT_WAR_ROOM_PROMPT.md` for the current draft-room milestone.
7. Add `PSE_API_BASE_URL` as a server-side secret / environment value.
8. Keep `GEMINI_API_KEY` server-side only. AI Studio can provision this secret for Gemini-enabled Build applications.
9. Never put ESPN `SWID` or `espn_s2` credentials in client code. They belong behind the Python/server boundary.
10. Run the application and verify `/api/health` plus the PSE `/health` endpoint.
11. Validate the deterministic product with Gemini disabled.
12. Deploy to Cloud Run only after provenance, stale-data, and error states have been tested.

## First build milestone: Draft War Room

The current priority is not another generic dashboard. Build the interface described in:

- `docs/product/draft_war_room_frontend.md`
- `ai_studio/DRAFT_WAR_ROOM_PROMPT.md`

The Draft War Room should let the user select 2 to 5 available players and compare:

- raw football projection;
- league-specific inherent value;
- positional scarcity / replacement cliff;
- fit into the current roster;
- probability of surviving to the next pick;
- team-level simulation impact once that model is available.

All leagues must derive settings from live platform snapshots when available. This is especially important for 2QB and superflex because quarterback replacement value changes radically with starter demand.

## Gemini responsibilities

Gemini may:

- translate natural-language questions into typed tool calls;
- compare tool outputs;
- explain model uncertainty and reason codes;
- construct a sequence of league queries;
- compare draft candidates across several dimensions;
- summarize trade and waiver alternatives;
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
- use one-QB rankings as a hidden proxy for 2QB value.

## Tool design

The existing Node server should remain a thin Gemini/tool boundary over the Product API.

Existing tool concepts include:

- `get_league_context`
- `get_player_board`
- `get_trade_suggestions`
- `get_waiver_board`
- `get_optimized_lineup`

The draft milestone should add or prepare for:

- `get_live_draft_board`
- `compare_draft_candidates`
- `get_my_roster`
- `get_recent_draft_picks`
- `get_player_detail`
- `get_model_evidence`

Function tools should be small, typed, read-only, and deterministic. The model chooses the tool; the application executes it; Gemini explains the returned result.

Use structured outputs for the final response when the React client needs stable fields such as:

```text
recommendation
best_raw_projection
best_league_value
best_roster_fit
best_pick_now
assumptions
uncertainties
supporting_tool_results
```

## Source-of-truth hierarchy

Use this hierarchy whenever data conflicts:

1. current live platform snapshot for league rules, ownership and completed picks;
2. current versioned Python prediction artifact for projections;
3. deterministic league-value / draft calculations;
4. timestamped market ADP for pick timing;
5. validated intelligence evidence;
6. Gemini explanation.

Gemini is never allowed to override levels 1 through 5 with a plausible narrative.

## Freshness handling

The UI must expose both platform freshness and model freshness.

Recommended states:

- `LIVE`: recent platform snapshot and valid projection artifact;
- `STALE`: last valid data retained, refresh overdue or enrichment failed;
- `HISTORICAL`: intentionally replaying a past snapshot;
- `SYNTHETIC DEMO`: development fixture only;
- `UNAVAILABLE`: no trustworthy projection / league artifact exists.

Do not replace stale live data with demo values.

## Prompt evaluation

Create a regression set containing:

- ambiguous player names;
- two leagues with different scoring;
- the same player compared in 8-team and 12-team 2QB formats;
- missing projections;
- missing ADP;
- stale injury data;
- stale platform snapshot;
- a positional run before the user's next pick;
- a player with strong raw projection but weak roster fit;
- a player with lower raw projection but severe positional scarcity;
- a request for a trade that harms the other manager;
- requests to invent certainty;
- multi-step queries such as “compare these three players, tell me who I can wait on, and show what changes in my starting roster.”

Score separately:

- tool selection correctness;
- argument correctness;
- factual grounding;
- agreement with deterministic ranking fields;
- uncertainty language;
- source/provenance visibility;
- usefulness under a live draft clock.

## AI Studio iteration workflow

For each AI Studio iteration:

1. ask the agent to inspect the existing implementation before editing;
2. make one coherent product change at a time;
3. preserve the Python calculation boundary;
4. run the frontend build;
5. test missing/stale API states;
6. test Gemini-off fallback behavior;
7. inspect diffs before syncing changes back to GitHub.

The product should become easier to interrogate without allowing the language model to become an unvalidated numerical oracle.
