# Reliability and Live Draft Decision Layer

This document defines the second reliability/usability wave built on top of the research Player State Graph.

The governing principle is simple: **a forecast can be numerically plausible and still be unsafe to present with strong language**. Data may be stale, a role may be changing, the predictive interval may be very wide, the consensus may disagree sharply, or a live draft recommendation may depend on an unrealistic assumption about who survives to the next pick.

The system now exposes those failure modes instead of hiding them behind one ranking number.

## 1. Forecast trust report

`player_state/trust.py` adds an explicit presentation guardrail around the Player State Graph.

It scores seven dimensions:

- evidence freshness
- role-state maturity
- role stability
- predictive sharpness
- Monte Carlo support
- expert agreement
- residual variance control

The output is:

- `score` from 0 to 100
- `grade` A/B/C/D
- `action_policy`: `ACT`, `LEAN`, `MONITOR`, or `VERIFY_DATA`
- machine-readable flags
- evidence age
- relative interval width
- component scores

Important: this is **not another player-value model**. Low trust does not mean a player is bad. It means the recommendation should be communicated more cautiously.

### Hard warning examples

- `STALE_EVIDENCE`
- `LOW_MONTE_CARLO_SUPPORT`
- `MISSING_EVIDENCE_FRESHNESS`
- `IMMATURE_ROLE_STATE`
- `ROLE_CHANGE_RISK`
- `WIDE_PREDICTIVE_INTERVAL`
- `HIGH_EXPERT_DISAGREEMENT`

`ReliablePlayerStateForecastService` wraps the existing research forecast service and returns the forecast and trust report together.

## 2. Correlated draft-room simulator

The original live draft board includes a transparent normal-ADP survival approximation. That baseline is useful, but it treats player survival independently.

Real rooms are not independent:

1. a drafted player disappears from every future choice,
2. positional runs change the remaining pool,
3. 2QB and deep-flex formats create different aggregate demand,
4. the value of waiting is determined by the *joint set* of players that survives.

`fantasy/draft_room.py` adds a research-only Monte Carlo room model. Each simulated room:

- samples latent draft position from player ADP uncertainty,
- removes players sequentially through the manager's next pick,
- applies a modest league-roster positional-demand pressure,
- tracks correlated player survival,
- records expected same-position supply at the next turn,
- calculates expected best same-position VORP available if the manager waits.

Outputs include:

- `room_survival_to_next_pick`
- `room_survival_standard_error`
- `room_position_wait_value`
- `room_position_wait_loss`
- `room_expected_position_supply_next_pick`
- `room_market_imputed`

Missing ADP is not silently accepted. It is imputed from the league-specific decision board and marked so the confidence layer can penalize it.

## 3. Guarded live draft advisor

`fantasy/draft_advisor.py` combines the stable live board with the room simulator.

It preserves the original `draft_action` and adds:

- `room_challenger_score`
- `room_rank`
- `room_rank_delta`
- `room_vs_analytic_survival_gap`
- `draft_reliability_score`
- `draft_reliability`
- `draft_reliability_reasons`
- `guarded_draft_action`

The room model is explicitly marked `room_challenger_promoted = False`.

The guarded action can become more conservative when:

- scoring coverage is incomplete,
- market ADP is imputed,
- analytic and Monte Carlo survival disagree sharply,
- projection uncertainty is high,
- Monte Carlo support is noisy.

This creates a useful distinction during a live draft:

> **DRAFT NOW** means the baseline ranking is strong.
>
> **VERIFY** means the system does not currently have enough agreement/support to justify a confident click under the draft clock.

## 4. One-command draft workflow

Use the dedicated script:

```bash
python scripts/run_live_draft_advisor.py \
  --projections artifacts/predictions/season_board.parquet \
  --league configs/fantasy/8_team_ppr_2qb_expanded.yaml \
  --draft-slot 4 \
  --current-pick 12 \
  --rounds 18 \
  --drafted RB1,WR1,QB1 \
  --roster QB1 \
  --room-simulations 1200
```

For a 12-team half-PPR median league, switch the league file:

```bash
--league configs/fantasy/12_team_half_ppr_median.yaml
```

The command writes:

- `artifacts/reports/live_draft_board.csv`
- `artifacts/reports/live_draft_board.json`

and prints the top recommendations with baseline rank, room rank, survival estimates, wait loss, guarded action, reliability score, and reasons.

## 5. What should be calibrated next

The correlated room model is a better structural hypothesis, not evidence of superiority yet.

The next historical draft benchmark should archive real platform drafts and evaluate:

### Survival calibration

For every player/pick pair:

- Brier score for survival to next pick
- log loss
- calibration curves
- error by draft round
- error by position
- error by league type

Compare:

```text
normal ADP survival baseline
platform empirical survival
correlated room simulator
correlated room simulator + opponent roster state
```

### Draft decision quality

Replay each historical room and compare:

- realized VORP lost by waiting
- best-player-available regret
- positional tier regret
- managed-lineup season value
- playoff/championship probability under downstream season simulation

### Ablations

Test separately:

- ADP uncertainty only
- + league positional demand
- + drafted-position counts
- + opponent roster needs
- + platform-specific drafting tendencies

Do not promote the room challenger until it wins these frozen replays with stable gains across league types.

## 6. Reliability program beyond the draft

The same trust contract should be applied to lineups, waivers, and trades.

Every decision-facing response should eventually include:

```text
recommendation
expected utility
main alternative
confidence/trust grade
freshness
model disagreement
uncertainty driver
what would change the recommendation
```

For trade and waiver decisions, the correct final unit remains downstream league utility: change in optimized weekly points, playoff probability, and championship probability under paired correlated season simulations.

## Scientific boundary

This reliability wave deliberately adds **more reasons for the system to say "I am not sure"**.

That is a feature. A fantasy decision engine becomes more useful when it knows the difference between:

- a volatile player,
- a genuinely close decision,
- stale or missing data,
- model disagreement,
- and a strong actionable edge.

The production champion remains unchanged until historical evidence clears the existing promotion gates.
