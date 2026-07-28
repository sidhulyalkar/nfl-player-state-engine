# Google AI Studio Build prompt

Build and iteratively refine the existing full-stack web application in `apps/gemini-fantasy-console` into a polished fantasy football intelligence product called **Fourth Down Lab**.

## Architecture constraints

- Preserve the React client and Node server structure.
- The Python NFL Player State Engine is the source of truth and is available through `PSE_API_BASE_URL`.
- Keep `GEMINI_API_KEY` server-side only.
- Gemini must use function calls to retrieve league, player, trade, waiver, lineup, NFL-state, and model evidence before making factual claims.
- Do not calculate projections or trade values in the browser or with Gemini.
- Retain a graceful demo-data mode when the Python API is unavailable.

## Required views

1. Command Center with roster floor, median, ceiling, risk, alerts, power ranking, and highest-leverage moves.
2. League Picture with every team, record, roster strength, positional heatmaps, ownership, free agents, and playoff state.
3. Player Lab with projection fan charts, opportunity funnel, role trajectory, matchup context, ownership, comparable players, and evidence timeline.
4. Trade Lab with drag-and-drop players, before/after legal lineups, both teams' distributions, fairness, mutual benefit, confidence, suggested trades, and counteroffers.
5. Opportunity Wire with free agents, role growth, vacated usage, breakout probability, expected opportunity duration, and FAAB ranges.
6. Lineup Lab with legal optimization, floor/ceiling risk controls, matchup win probability, and correlated scenario simulation.
7. NFL State with team records, dynamic strength, point differential, coaching and quarterback changes, pace, pass rate, personnel, injuries, and game environments.
8. Model Lab with calibration, backtests, model version, data freshness, missing sources, and champion/challenger history.

## Design

- Preserve the dark analytical aesthetic, mint and violet accents, clear typography, and information-dense cards.
- Prefer fan charts, probability bands, heatmaps, small multiples, and delta waterfalls.
- Avoid decorative charts that do not aid a decision.
- Make ownership, availability, freshness, and uncertainty visible on every relevant surface.
- Desktop is the primary workspace, but keep mobile lineup, waiver, alert, and trade views excellent.
- Use accessible colors, keyboard navigation, useful empty states, skeleton loading, and error recovery.

## Gemini Copilot

Create a persistent Copilot drawer that can answer questions such as:

- “What is the highest-leverage move for my roster?”
- “Find a fair RB trade that preserves my playoff ceiling.”
- “Why did this player's projection change?”
- “Which free agent has the best chance to earn a durable role?”
- “Optimize my lineup because I am projected to lose by 18.”

Every answer must cite the tool outputs used, state material uncertainty, and offer concrete actions.

## Data and state

- Add a league onboarding flow for Sleeper league ID, Yahoo OAuth placeholder, Fleaflicker, and CSV upload.
- Support multiple leagues and persist the selected league and roster.
- Add filters for position, NFL team, owner, free agent, availability, floor, ceiling, role growth, and model confidence.
- Make tables exportable.

Start by ensuring the current project builds, then improve one view at a time without breaking the server-side tool boundary.
