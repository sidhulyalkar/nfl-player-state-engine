# Google AI Studio Build prompt

Build and iteratively refine the existing full-stack web application in `apps/gemini-fantasy-console` into a polished fantasy football intelligence product called **Fourth Down Lab**.

## Current priority: Draft War Room

The first product surface to make excellent is the live Draft War Room. Read and follow:

- `ai_studio/DRAFT_WAR_ROOM_PROMPT.md`
- `docs/product/draft_war_room_frontend.md`
- `docs/modeling/draft_intelligence_models.md`
- `docs/product/live_draft_room.md`

The user plays in multiple leagues with materially different settings, including 2QB formats. The app must derive value from each live league's actual roster slots and scoring rules. Never assume generic one-QB rankings transfer to 2QB or superflex.

## Architecture constraints

- Preserve the React client and Node server structure.
- The Python NFL Player State Engine is the numerical source of truth and is available through `PSE_API_BASE_URL`.
- Keep `GEMINI_API_KEY` server-side only.
- Gemini must use function calls to retrieve league, player, draft, trade, waiver, lineup, NFL-state, and model evidence before making factual claims.
- Prefer structured outputs for typed Gemini responses consumed by the UI.
- Do not calculate projections, VORP, replacement levels, roster-fit utility, draft survival, trade values, or lineups in the browser or with Gemini.
- Retain a graceful, explicitly labeled demo-data mode when the Python API is unavailable.
- A deterministic feature must remain usable when Gemini is unavailable.

## Required views

1. **Draft War Room** with live room state, available-player board, current roster, 2-to-5-player comparison tray, league-specific scarcity, roster fit, tier cliffs, and survival-to-next-pick.
2. Command Center with roster floor, median, ceiling, risk, alerts, power ranking, and highest-leverage moves.
3. League Picture with every team, record, roster strength, positional heatmaps, ownership, free agents, and playoff state.
4. Player Lab with projection fan charts, opportunity funnel, role trajectory, matchup context, ownership, comparable players, and evidence timeline.
5. Trade Lab with drag-and-drop players, before/after legal lineups, both teams' distributions, fairness, mutual benefit, confidence, suggested trades, and counteroffers.
6. Opportunity Wire with free agents, role growth, vacated usage, breakout probability, expected opportunity duration, and FAAB ranges.
7. Lineup Lab with legal optimization, floor/ceiling risk controls, matchup win probability, and correlated scenario simulation.
8. NFL State with team records, dynamic strength, point differential, coaching and quarterback changes, pace, pass rate, personnel, injuries, and game environments.
9. Model Lab with calibration, backtests, model version, data freshness, missing sources, and champion/challenger history.

## Draft War Room interaction model

The user will commonly select several players and ask which to draft. The UI and Copilot must keep these concepts separate:

- raw football projection;
- league-specific inherent value / VORP;
- positional scarcity and replacement cliff;
- fit on the user's current roster;
- cost of passing and probability of surviving to the next pick;
- experimental team-level season impact when a validated simulator exists.

The final recommendation may differ from the best raw projection. Make the disagreement visible.

For 2QB leagues, explicitly display mandatory QB starter demand, replacement rank, tier depletion, QB starter-security when available, and the consequence of waiting. Do not merely multiply QB projections by an arbitrary premium.

## Design

- Preserve the dark analytical aesthetic, mint and violet accents, clear typography, and information-dense cards.
- Make the Draft War Room fast, compact, and number-forward rather than chat-first.
- Prefer fan charts, probability bands, heatmaps, small multiples, tier separators, aligned comparison rows, and delta waterfalls.
- Avoid decorative charts that do not aid a decision.
- Make ownership, availability, freshness, provenance, and uncertainty visible on every relevant surface.
- Desktop is the primary workspace, but keep mobile player compare, roster, waiver, alert, and trade views excellent.
- Use accessible colors, keyboard navigation, useful empty states, skeleton loading, stale-data states, and error recovery.

## Gemini Copilot

Create a persistent Copilot drawer that can answer questions such as:

- “I am between these three players. Who is the best pick now and why?”
- “Which of these QBs is actually worth the 2QB scarcity premium?”
- “Can I wait on this WR until my next pick?”
- “What is the highest-leverage move for my roster?”
- “Find a fair RB trade that preserves my playoff ceiling.”
- “Why did this player's projection change?”
- “Which free agent has the best chance to earn a durable role?”
- “Optimize my lineup because I am projected to lose by 18.”

Every answer must cite or identify the deterministic tool outputs used, state material uncertainty, and offer concrete actions.

Gemini is an explanation and orchestration layer. Custom football and draft models are trained in Python. Do not present Gemini fine-tuning as the predictive architecture.

## Data and state

- Add league onboarding for Sleeper username / league ID, ESPN league ID with server-side credential handling, and CSV/manual fallback.
- Support multiple leagues and persist the selected league and roster.
- Treat live platform scoring and roster settings as authoritative when available.
- Add filters for position, NFL team, owner, free agent, availability, floor, ceiling, role growth, model confidence, draft action, and survival probability.
- Make tables exportable.
- Never expose ESPN private session credentials or Gemini API keys to the browser.

## Product API direction

Prefer small typed read-only tools. The Draft War Room should ultimately consume server-generated endpoints conceptually equivalent to:

```text
GET  /v1/leagues/{league_id}/draft/board
POST /v1/leagues/{league_id}/draft/compare
```

If the Python API does not yet expose a desired field, show it as unavailable and preserve the source-of-truth boundary rather than recreating the formula in TypeScript.

## Validation

Test at minimum:

- 12-team 2QB half-PPR median scoring;
- 8-team PPR with 2QB / 3RB / 3WR / 3FLEX;
- missing ADP;
- stale platform snapshot;
- missing projection artifact;
- a positional run before the user's next pick;
- a strong player who is likely to survive until the next pick;
- Gemini disabled while the deterministic product remains usable.

Start by ensuring the current project builds, then implement the Draft War Room without breaking the server-side tool boundary. Improve the remaining views after the draft workflow is reliable.
