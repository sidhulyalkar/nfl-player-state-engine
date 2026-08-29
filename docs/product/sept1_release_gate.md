# Sept. 1 draft release gate

The draft product needs one operator-facing answer that is harder to misread than a collection of individually green dashboards. This gate combines projection authority, byte integrity, source freshness, current NFL state, market identity health, verified external-only special-teams support and exact fantasy league contracts into one release verdict.

## Verdicts

### READY

`READY` means every declared league is fully qualified under the current projection artifact and current NFL Hub state.

It requires:

- the package release identity to be frozen on the v0.17 line;
- an immutable champion projection bundle with `production_approved` authority;
- fresh byte verification of that bundle;
- a declared and fresh projection source cutoff;
- a current NFL Hub snapshot with the expected observational authority;
- no required NFL Hub source failure;
- sufficient current roster coverage;
- sufficient exact-ID redraft market coverage;
- exact league scoring support for every required starting position;
- complete league valuation and identity readiness.

### PROVISIONAL

`PROVISIONAL` is deliberately narrow. It does **not** weaken projection authority or redefine a blocker as model success.

It is legal only when all core release requirements above are satisfied and every remaining exception is isolated to an explicitly non-model lane:

- K/DST are the only required positions that remain missing or scoring-inexact;
- a fresh special-teams snapshot with authority exactly `external_market_only` exists;
- that snapshot declares `model_fields_present=false` and contains sufficient current entries for **every** unresolved K/DST position; and/or
- the NFL Hub is degraded only because an optional source is unavailable while required roster truth, freshness and market-identity gates still pass.

Missing, stale, partial, model-labelled or otherwise invalid K/DST market evidence does **not** unlock a provisional release. The league remains `BLOCKED`.

The intended Sept. 1 example is a fully qualified QB/RB/WR/TE board with current NFL state, while K/DST are shown separately as external market-only late-round guidance. The UI must not label K/DST values as model q50, VORP or production-model output.

### BLOCKED

`BLOCKED` means the core draft board should not be treated as qualified. Examples include:

- no immutable production champion;
- artifact hash/integrity failure;
- stale projection source cutoff;
- stale/unavailable NFL Hub state;
- required NFL source failure;
- poor redraft market identity coverage;
- duplicate/missing projection identities;
- incomplete valuation;
- any exact-scoring gap for QB, RB, WR or TE;
- K/DST exceptions without a fresh, complete `external_market_only` support artifact;
- any other league-readiness blocker that is not solely a verified market-only K/DST exception.

## Operator

The operator accepts every distinct league contract that must be supported:

```bash
python scripts/check_sept1_release_readiness.py \
  --projections artifacts/predictions/product_player_values.csv \
  --league configs/fantasy/8_team_ppr_2qb_expanded.yaml \
  --league configs/fantasy/12_team_half_ppr_median.yaml \
  --nfl-hub data/product/nfl_hub/current.json \
  --special-teams-market data/product/special_teams_market/current.json \
  --registry-root artifacts/registry \
  --bundle-root artifacts/production/sept1 \
  --champion-target preseason_player_values_2026 \
  --json-output artifacts/reports/sept1_release_readiness.json \
  --allow-provisional
```

Omitting the immutable champion arguments does not make the tool more convenient. It intentionally returns an unverified projection authority and therefore `BLOCKED`.

When a declared league needs K or DST and those positions are not model-qualified, omitting `--special-teams-market` also remains `BLOCKED`. The special-teams artifact is evidence for the isolated fallback lane, not a substitute for projection authority.

Use `--strict-ready` for the final freeze. It exits nonzero for both `PROVISIONAL` and `BLOCKED`.

Use `--allow-provisional` during launch rehearsal. It exits nonzero only for `BLOCKED`, while retaining every provisional reason in the JSON output.

## Freeze sequence

The Sept. 1 release should be frozen in this order:

1. finish the preregistered preseason benchmark without changing its gates after seeing results;
2. choose the season-value lane based on that result;
3. materialize the exact 2026 projection artifact;
4. register it as an immutable bundle;
5. review evidence and, only if justified, create a `production_approved`, activation-eligible bundle;
6. manually promote the exact bundle to the declared champion target;
7. refresh NFL Hub after roster cutdown/waiver churn;
8. refresh and freeze the external-only K/DST market snapshot when required by a league;
9. run this release gate across every real league contract;
10. rehearse the live Draft Room using the exact frozen artifacts;
11. bump/freeze v0.17.0 and rerun `--strict-ready` immediately before the release candidate is used.

A green CI run is necessary but not sufficient. The release verdict is tied to the actual projection bytes, actual NFL snapshot, actual special-teams fallback evidence and actual league contracts that will be used at draft time.
