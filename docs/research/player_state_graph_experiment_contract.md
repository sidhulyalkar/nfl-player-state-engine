# Player State Graph experiment contract

## Primary question

Does explicit latent player-state structure improve held-out fantasy decision quality over the frozen direct quantile champion without sacrificing calibration, point-in-time validity, or interpretability?

## Frozen comparison families

1. rolling-stat baseline;
2. position-prior baseline;
3. current direct production champion;
4. Player State Graph challenger;
5. generative football world challenger;
6. external consensus, when archived point-in-time forecasts exist;
7. historically learned forecast fusion.

## Primary forecast metrics

- mean q10/q50/q90 pinball;
- q10-q90 empirical coverage;
- mean interval width;
- CRPS when Monte Carlo draws are available;
- rank correlation;
- active-status Brier score;
- role-change lead time.

All metric deltas are paired on the same player-week and bootstrapped by season/week or game block.

## Primary decision metrics

- lineup regret;
- waiver points over replacement and missed-candidate regret;
- FAAB efficiency;
- trade playoff/championship probability delta;
- transaction probability-of-help;
- draft value over replacement and roster-construction outcome.

## Preregistered slices

- QB/RB/WR/TE;
- Weeks 1-4;
- post-injury/role-change windows;
- low/medium/high regime maturity;
- Wednesday vs Sunday horizon;
- high vs low availability uncertainty;
- high vs low direct/world/consensus disagreement.

## Negative controls

- shuffled player identity within position/team-season where appropriate;
- permuted role evidence within team-season;
- publication timestamps shifted beyond the cutoff, which must be rejected;
- source-family labels routed to an illegal latent target, which must fail closed;
- consensus forecasts time-shifted from after kickoff, which must be rejected.

## Promotion gate

A challenger needs, at minimum:

- Evidence Tier 3;
- positive paired effect above the declared minimum useful effect;
- bootstrap confidence interval clearing the gate;
- no material calibration/sharpness regression;
- >80% eligible historical/live data availability;
- passed negative controls;
- no severe season/position/week inconsistency;
- FDR-adjusted q-value within the registered threshold when multiple challenger families are tested.

Live production authority is not available before Tier 4 shadow-season evidence.

## v0.16 interaction

This work does not redefine the v0.16 terminal-family experiment or its v0.17 routing decision. The Player State Graph is an independent player-forecast research spine that can progress in parallel. Results from v0.16 decide game-world authority; results here decide player-state and fantasy-decision authority.
