# October 25, 2026 RedZone experimental live-score qualification

## Boundaries

The existing **Delayed verified schedule** view is fed by nflverse's published
`schedules/games.csv`, usually no more often than five minutes, and deliberately
does not claim live possession, score status or clock.

This branch adds a distinctly labeled **Experimental live scores** view.
The optional local adapter tests ESPN's publicly reachable, **undocumented**
Site scoreboard endpoint. It is not an official/supported API, is not
licensed for redistribution by this project, and could be blocked or changed
at any time. **Do not deploy or commercialize the adapter without provider
permission, a terms review, and an approved commercial data contract.**

No scraper, HTML replayer, NFL.com API token extraction, tracking feed,
private partner API, or raw provider response export is included.

## Local startup

From the repository root, after checking your local terms/usage requirements:

    git fetch origin
    git switch --track origin/feat/redzone-live-score-pilot
    npm ci --include=optional
    PSE_EXPERIMENTAL_LIVE_SCORES=1 npm run dev:full

Go to `http://127.0.0.1:3000/?workspace=sunday`.

The default tab is **Experimental live scores**, with **Delayed verified
schedule** one click away. An explicit opt-in is required: if disabled, the
experimental tab shows HTTP 403 and instructions, while the delayed board
remains accessible. Both views retain independent source identifiers.

To see raw *normalized* metadata without storing a raw provider JSON file:

    PSE_EXPERIMENTAL_LIVE_SCORES=1 \
      .venv/bin/python scripts/qualify_experimental_live_scores.py --season 2026 --week 7

Alternatively:

    curl -s http://127.0.0.1:3000/api/pse/v1/gameday/experimental-live-scores?season=2026

Network tests require a real internet-connected Mac and provider availability;
GitHub CI exercises a synthetic, strict-schema fixture only.

## What is measured

- Canonical NFL game IDs derived from requested season + verified source week
  + home/away teams, with explicitly mapped abbreviation exceptions.
- Provider-reported score, period, display clock, pre/in/post state,
  kickoff and provider event ID. The display clock is **not locally ticked**.
- Every server cache entry is in process memory, checked at most once
  per 30 seconds per season/week. Raw source JSON is not persisted.
- Each response carries an exact fetch timestamp, cache age, provider label,
  stale flag, fetch/throttle state, and explicit `live_play_by_play=false`
  / `live_tracking=false`. After 90 seconds or a failed refresh,
  previous data is labeled stale, never silently promoted.
- Frontend updates only report score differences or status transitions
  between newer source timestamps and the same verified game identity.
  Score decreases are legitimate corrections. The first snapshot is
  baseline only. No touchdown, fourth-down conversion, catch, defensive
  scheme, drive, possession, fantasy point or player attribution is inferred.

## October 25 live acceptance

1. Compare the number of in-progress games and matchup identities to
   [NFL's public scores page](https://www.nfl.com/scores) or another
   independently updated scoreboard while Sunday afternoon games run.
2. Start the adapter, inspect `source.fetched_at_utc` and `stale` and
   verify at least one game state and quarter/clock against the independent
   scoreboard. **Clock differences do not establish which provider is right.**
3. Leave the page running for two or more 30-second intervals. Check that
   a new fetched timestamp appears, and that a subsequent *observed*
   score change produces exactly one update entry.
4. Verify refresh button does not defeat backend 30-second throttling.
5. Disconnect the network after a successful fetch. Confirm the
   stale flag and clear error. Re-enable the network and verify recovery.
6. Switch to the delayed view; confirm it retains the prior five-minute
   source contract and does **not** display invented quarter or possession.
7. Check a game with `pre` state: 0-0 placeholders are **not** displayed
   as verified live scores.
8. In the React UI, exercise watched-game and in-progress filters.
   During a 403 or provider block, verify the user can switch back to
   the delayed board. Never suppress failed provider checks.

## Regression tests

    python -m pytest -q tests/product/test_experimental_live_scores.py
    cd apps/gemini-fantasy-console
    npm run build
    npm run test:field3d

Full repository CI and browser screenshot smoke are mandatory for merge.

## Next stage

A true live play/drive commentary engine needs a **licensed, documented**
play-by-play data provider, validated event IDs, corrections/idempotency,
source timestamps, NFL player IDs, and an explicit rights contract. The
experimental scoreboard is *not* that provider. Historical Play Lab
geometric replay is a separate source domain.
