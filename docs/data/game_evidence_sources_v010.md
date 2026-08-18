# v0.10 Game Evidence Sources

## Principle

Collect broad evidence, but encode **availability time and authority** before encoding football meaning.

A rich source that arrives after the prediction cutoff is not a valid live feature.

## Source tiers used by the code

### Live

**nflverse play-by-play**

Primary evidence for state transitions, down/distance, score, clock, field position, play family, EPA, pace, passer/rusher/receiver opportunity and realized outcomes.

**schedules/game environment**

Opponent, venue and pregame game context. Preserve snapshot time for any fields that can change before kickoff.

**depth charts**

Useful role evidence when timestamps are available. Never replace timestamped history with a latest-only depth chart during backtesting.

### Live fail-soft

**snap counts**

Useful for participation/role state. A source outage must not fail the core projection build.

**Next Gen Stats aggregates**

Useful efficiency evidence such as expected rushing/receiving outcomes. Treat weekly aggregates as completed-game evidence available only after their publication time.

**FTN charting through nflverse**

Potential play-structure evidence including motion, play action, RPO, screen and pressure/blitz variables. Preserve upstream availability timestamps and attribution requirements.

### Retrospective only unless availability is proven

**participation data**

Formation, personnel, defenders in box and players-on-play are extremely useful for representation learning and retrospective diagnosis. Current nflverse documentation notes that recent FTN-derived participation data may only be provided after the postseason. Therefore v0.10 labels this source `RETROSPECTIVE` and excludes it from live 2026 prediction by default.

Retrospective data can still answer valuable questions:

- Which formation/personnel states are predictive enough to justify sourcing them live?
- How much would route/personnel knowledge improve player opportunity prediction?
- Which defensive box/personnel interactions are worth licensing or collecting separately?

### Manual/licensed/timestamped

**official injury/availability evidence**

The existing evidence pipeline should ingest official reports or authorized structured feeds with capture time. Do not assume the historical nflverse injury loader is a current 2026 feed.

**coach/play-caller registry**

Maintain head coach, coordinators, actual offensive/defensive play caller, effective week, capture timestamp and source. Midseason play-caller changes must be represented as state transitions.

**pregame spread/total**

Use as an external probabilistic sensor of likely game environment. Store capture time. Never use closing lines to backfill an earlier prediction unless the experiment explicitly studies closing information.

## Additional evidence worth pursuing

These are intentionally diverse because player fantasy outcomes emerge from multiple interacting systems.

### Offensive line state

- projected starters;
- continuity by position;
- injuries/limited practice;
- pressure/sack responsibility history;
- run-block/pass-block performance where licensed.

Expected effect: QB efficiency, time to throw, deep-shot rate, RB efficiency and play-caller adaptation.

### Defensive front and coverage state

Where legitimate structured data exists:

- box counts;
- pressure/blitz tendency;
- man/zone or shell proxies;
- explosive plays allowed by concept;
- slot/outside matchup behavior;
- target funnel by position/alignment.

The goal is not a deterministic matchup grade. It is a distribution over likely defensive responses.

### Formation/personnel sequence

Rather than a static rate, model transitions such as:

```text
11 personnel shotgun pass
 -> successful explosive
 -> same look / counter / tempo change
```

and

```text
heavy personnel short-yardage failure
 -> next short-yardage concept
```

This is a promising representation-learning target when point-in-time formation data is available.

### Drive and halftime adaptation

Features can include:

- opening-drive script;
- pass/run shift after score changes;
- second-half change relative to first half;
- repeated concept success/failure;
- pace changes;
- target concentration changes;
- pressure response.

Do not call these internal intentions. They are observed conditional policy changes.

### Player role evidence

- first-team reps;
- snap share;
- route participation;
- target per route;
- slot/outside/backfield alignment;
- third-down role;
- two-minute role;
- goal-line role;
- designed QB rushes;
- pass protection;
- return from injury participation ramp.

The v0.9 evidence-authority system should feed these as latent-state updates rather than as raw sentiment.

### Environment

- weather trajectory rather than a single daily forecast;
- wind and precipitation near kickoff;
- roof/open/closed state;
- surface;
- travel distance/time zones;
- short week / bye / rest advantage;
- altitude and extreme temperature.

These should start as low-authority/context features and earn weight through ablation.

### Officials and penalty environment

Referee crew tendencies can be tested as a small contextual feature family for pace, drive continuation and penalties. This is a classic example of a plausible feature that should remain low priority until a frozen ablation demonstrates value.

### Market disagreement

Pregame spread, total and player/team props can act as independent probabilistic sensors. Track:

- model vs market difference;
- change over time;
- whether disagreement resolves toward model or market;
- calibration conditional on disagreement size.

Do not use the market as ground truth or silently tune the football model to reproduce it.

## Capture contract

Every external evidence row should be able to answer:

- what source produced this?
- when was it observed?
- what game/player/team does it refer to?
- was it genuinely available before prediction cutoff?
- is it structured observation, report, quote, analysis or speculation?
- what transformation generated the feature?
- what model/version consumed it?

If those questions cannot be answered, the data should not silently enter a production model.
