# Intelligence evidence and promotion experiments

## Evidence families

### Official availability

`OfficialAvailabilityEvidence` supports:

- practice participation;
- official game designation;
- inactive lists;
- injured reserve and PUP;
- transactions and activations;
- depth-chart role and rank;
- coach-confirmed workload fraction.

`build_official_availability_features` emits cumulative point-in-time snapshots and retains separate family columns so each source can be activated independently.

### Structured news

`extract_news_claims` creates evidence-backed claims for:

- workload limits;
- starter, backup and committee roles;
- increased routes or targets;
- coach-announced role changes;
- travel complications;
- weather complications.

Every claim retains source URL, publication and collection timestamps, evidence text, extractor confidence, source reliability and originating document ID.

### Public player context

Persona/context features remain conservative observations of public language and visibility. They are not psychological diagnoses. Supported dimensions include training, recovery, matchup preparation, role discussion, team/leadership language, media visibility, commercial share, source diversity and evidence strength.

## Point-in-time joins

`attach_intelligence_families` joins each family independently using the latest snapshot before kickoff minus the configured safety lag. Family-specific as-of timestamps and found/not-found indicators are preserved.

## Soft-feature deployment

`IntelligenceResidualAdjuster` is the first deployment mode for news and public context:

- trains only on frozen out-of-sample numerical predictions;
- caps center movement to 25% of baseline half-width;
- limits width scaling to 0.85–1.15 by default;
- records the actual shift and width scale on every prediction.

Soft evidence cannot replace the numerical engine or directly declare that a player is motivated, mentally stronger or destined to outperform.

## Required ablations

The benchmark runner creates:

1. numerical baseline;
2. official availability only;
3. objective opportunity only;
4. news only;
5. public context only;
6. combined intelligence;
7. shuffled-player control;
8. shifted-time leakage control.

The shifted-time control intentionally moves future intelligence backward and is never promotion-eligible. Its role is to reveal how large an apparent gain leakage could manufacture.

## Promotion gate

Public context must:

- improve pinball loss beyond the objective opportunity reference;
- win at least the configured number of held-out seasons;
- not reproduce its gain under player shuffling;
- pass position-specific calibration and regression checks;
- retain source diversity and evidence provenance.

Run:

```bash
pse benchmark-intelligence-ablations \
  --features data/processed/weekly_features_with_all_intelligence.parquet \
  --target fantasy_points_ppr \
  --output-dir artifacts/reports/intelligence_ablations
```
