# Fantasy decision framework

A player does not possess one context-free fantasy value. Value is the expected improvement in a particular decision, relative to the alternatives available in that league.

## Shared probabilistic state

Every decision begins with the same state:

```text
active probability
→ snaps and routes
→ team plays and dropbacks
→ carries, targets and red-zone work
→ receptions, yards and touchdowns
→ weekly and rest-of-season outcome distributions
```

The engine should retain q10, q50 and q90 outcomes, plus source confidence and role uncertainty. Point rankings alone hide whether two players have similar medians but radically different floors and ceilings.

## Decision-specific utility

### Weekly start/sit

Prioritize conditional active probability, weekly floor/median/ceiling, matchup, game environment, and lineup context. A favorite with a narrow range can be preferable when protecting a lead; a volatile deep threat can be preferable when projected to trail.

### Waivers and FAAB

Measure upgrade over the weakest rostered alternative, not raw points. Include vacated opportunities, depth-chart promotion, role growth, schedule horizon, availability, breakout probability, and how long the role is likely to last.

### Trades

Compare rest-of-season VORP distributions, roster fit, replacement options, playoff weeks, correlated roster exposure, and injury risk. Two-for-one trades must account for the roster spot that becomes occupied or freed.

### Drafts

Use value over replacement, positional scarcity, market acquisition cost, roster construction, floor/upside balance, and portfolio correlation. Draft value is projection value minus the cost of acquiring the player at that point.

### Stashes and dynasty

Weight prospect priors, age, draft capital, college production, athletic profile, role-access probability, team fit, and multi-year upside. These rankings should differ materially from redraft rankings.

## Evaluation targets

The product should be judged on decisions, not only aggregate projection error:

- start/sit regret versus the best legal lineup;
- waiver points gained over the dropped player;
- FAAB efficiency and role-duration accuracy;
- trade value delta after replacement and roster-fit effects;
- draft value above market cost;
- calibration of breakout, active and top-N finish probabilities;
- ranking quality within the realistic candidate set available to the manager.

`pse fantasy-decision-board` implements separate utility functions for start/sit, waiver, trade, draft, stash and dynasty decisions. Treat these as transparent initial policies to benchmark, not eternal football commandments carved into a goalpost.
