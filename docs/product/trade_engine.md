# Trade engine requirements

## Current v0.6 implementation

`product/trades.py` evaluates both rosters before and after a proposal using:

- legal optimized starting lineups;
- league-relative player value;
- floor and ceiling;
- bench depth;
- positional balance;
- uncertainty-adjusted probability of improvement;
- fairness and mutual-benefit scores.

It can enumerate one-for-one and two-for-one candidates against complementary roster needs.

## Required evolution

### Rest-of-season simulation

Replace additive player values with correlated weekly simulations through the fantasy playoffs. Measure:

- expected wins;
- playoff probability;
- championship probability;
- lineup regret;
- injury concentration;
- bye-week coverage.

### Dynasty assets

Add:

- future rookie picks represented as distributions;
- age and contract curves;
- contender/rebuilder utility;
- taxi squads and keepers;
- replacement windows and roster churn.

### Acceptance model

Learn from anonymized proposed and accepted trades, while separating manager behavior from objective trade quality. Useful inputs include:

- value delta for each manager;
- positional need addressed;
- number of players and picks;
- manager transaction history;
- contender status;
- timing in season;
- recent player news and role changes.

The acceptance model should rank which fair trades are plausible. It should not redefine fairness according to who can be persuaded.

### Counteroffer generation

Search the Pareto frontier and explain which small change improves both fairness and acceptance likelihood:

- add a bench player;
- swap a draft round;
- reduce FAAB;
- exchange a redundant position;
- move from a volatile asset to a stable one.

### User-facing outputs

- Team A and Team B value distributions
- Legal lineup before and after
- Positional need heatmaps
- Floor/ceiling and playoff effects
- Fairness, mutual benefit, and confidence
- Key assumptions and missing evidence
- Three counteroffers
