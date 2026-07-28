# Google AI Studio implementation guide

## Recommended use

Use Google AI Studio Build mode to iterate on the React and Node application in `apps/gemini-fantasy-console`. Keep the Python Player State Engine deployed separately as a private or authenticated service.

## Setup

1. Push this repository to GitHub.
2. Open Google AI Studio Build mode.
3. Import the GitHub repository.
4. Point the agent to `apps/gemini-fantasy-console` and `ai_studio/BUILD_PROMPT.md`.
5. Add `PSE_API_BASE_URL` as a server-side secret.
6. AI Studio creates and manages `GEMINI_API_KEY` for new Gemini-enabled applications.
7. Run the app and verify `/api/health` and the PSE `/health` endpoint.
8. Deploy the frontend to Cloud Run when ready.

## Gemini responsibilities

Gemini may:

- translate natural-language questions into typed tool calls;
- compare tool outputs;
- explain model uncertainty and reason codes;
- construct a sequence of league queries;
- summarize trade and waiver alternatives;
- generate user-facing narratives and follow-up questions.

Gemini may not:

- invent projections or ownership;
- replace deterministic lineup optimization;
- calculate trade values outside the Product API;
- claim injuries or news without retrieved evidence;
- silently take transactions on a fantasy platform.

## Tool design

The starter Node server exposes five tools:

- `get_league_context`
- `get_player_board`
- `get_trade_suggestions`
- `get_waiver_board`
- `get_optimized_lineup`

Later tools should remain small, typed, and read-only until the product has explicit confirmation flows.

## Prompt evaluation

Create a regression set containing:

- ambiguous player names;
- two leagues with different scoring;
- missing projections;
- stale injury data;
- requests for a trade that harms the other manager;
- requests to invent certainty;
- multi-step queries such as “improve my RB room without weakening playoff ceiling.”

Score tool correctness, factual grounding, uncertainty language, and usefulness separately.
