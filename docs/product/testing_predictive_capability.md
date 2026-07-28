# Testing predictive capability and product decision value

## Two scoreboards

The project needs both a **forecast scoreboard** and a **decision scoreboard**.

A model can reduce player-point error without improving lineup, waiver, or trade choices. Conversely, a small point-forecast gain can be highly valuable if it correctly detects role transitions among replacement-level players.

## Forecast scoreboard

### Frozen weekly protocol

For every historical week:

1. Freeze a prediction cutoff, ideally Wednesday and again Sunday morning.
2. Use only information available before that cutoff.
3. Train on earlier weeks and seasons.
4. Archive raw model distributions and source manifests.
5. Compare against strong public and transparent baselines.
6. Reveal results only after the games complete.

### Required baselines

- Five-game rolling production
- Position prior
- Previous-week role
- Public consensus projection captured at the same timestamp
- Market implied game total and spread, timestamped
- Opportunity-only model
- Champion Player State Engine

Consensus and market inputs must be separate ablations so the engine's independent contribution remains visible.

### Metrics

For continuous player outcomes:

- MAE and RMSE
- Mean pinball loss at q10/q50/q90
- CRPS when full samples are available
- Interval coverage and width
- Calibration by target, position, projection timestamp, and availability state
- Spearman rank correlation
- Top-k precision for weekly breakout and bust classes

For availability and role transitions:

- Brier score and log loss
- Precision-recall curves
- Lead time before the role change becomes obvious in box scores
- False-alert rate

### High-value slices

- Rookies and players changing teams
- First games after teammate injuries
- Backup quarterbacks and quarterback changes
- New coaches and coordinators
- Players with recent snap or route jumps
- Weather extremes
- Short rest and travel
- Red-zone role changes
- Weeks 1–4, where priors matter most
- Fantasy playoffs

## Decision scoreboard

### Start/sit regret

For every roster-week:

```text
regret = optimal hindsight legal lineup points - recommended lineup points
```

Compare the engine with:

- highest platform projection;
- highest season average;
- highest recent average;
- user-submitted actual lineup when available.

Track average regret, median regret, catastrophic misses, and matchup win probability added.

### Waiver evaluation

For every suggested add:

- points above the dropped player over 1, 3, and 6 weeks;
- starts created above replacement;
- FAAB efficiency;
- opportunity duration;
- breakout precision;
- regret from ignored candidates.

### Trade evaluation

Because counterfactual acceptance is difficult, evaluate in layers:

1. **Retrospective value:** rest-of-season and playoff points before and after.
2. **Roster utility:** optimized lineup and depth changes, not raw player sums.
3. **Fairness:** both teams' realized and projected deltas.
4. **Human quality:** blind ratings from experienced managers.
5. **Acceptance proxy:** whether suggested trades resemble actual transactions among comparable roster states.

A good trade engine should create a frontier of options, not pretend one proposal is objectively compulsory.

### Draft evaluation

- Value over replacement by acquisition cost
- Best-ball and managed-lineup points
- Roster construction quality
- Injury-adjusted value
- Opportunity captured after the draft
- Calibration of rookie ranges

## Online shadow season

Before trusting the product:

- Run every league recommendation in shadow mode.
- Timestamp what the system knew.
- Record user decisions but do not overwrite them.
- Evaluate recommendations after 1, 3, and 6 weeks.
- Ask users whether explanations were useful independently of whether variance produced a win.

## Promotion gates

A new feature family advances only when it:

- improves at least three held-out seasons or a preregistered current season;
- improves the primary probabilistic metric;
- does not materially break calibration;
- improves at least one decision metric;
- survives shuffled-player and shifted-time controls;
- has adequate coverage and timestamp integrity;
- remains useful within relevant positions and role states.
