# Rookie, team structure and role integration

## Rookie priors

`build_prospect_features` combines:

- draft round and overall pick;
- position-standardized speed, burst, agility and size;
- optional breakout age, dominator rating, target/rush shares, yards per team pass attempt and early-declare status;
- evidence completeness, so a sparse workout profile is not treated as a complete negative measurement.

The rookie quantile model predicts a distribution and returns historical analogs. Draft capital remains the strongest initial prior in the scaffold, while athletic and college production features modify rather than overpower it.

## Team and coaching structure

`build_team_play_structure` creates leakage-safe rolling fingerprints for pace, neutral pass rate, red-zone pass rate, shotgun, no huddle, motion, and target/carry concentration. Coaching continuity can be joined through head-coach and offensive-coordinator change flags.

`score_player_scheme_fit` describes observable role-system compatibility. It does not reconstruct proprietary playbooks or infer private strategy. For example, a receiver receives a stronger environment score in a fast, pass-heavy, concentrated offense, while a running back receives a stronger score in a concentrated rushing environment.

## High-chance opportunities

The watchlist separates:

1. opportunity becoming available, such as vacated targets or an injured teammate;
2. ability to capture the role, such as snaps, pass-play participation and depth position;
3. role direction, such as recent growth or promotion;
4. reliability, such as active probability and uncertainty.

This produces auditable archetypes and reason codes rather than a mysterious breakout number.
