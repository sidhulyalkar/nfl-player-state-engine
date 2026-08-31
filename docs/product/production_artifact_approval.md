# Production artifact approval

The v0.17 production release uses a two-step authority transition. A challenger that clears the live release rehearsal is still not production authority, and CI is not allowed to make it one.

## 1. Derive production authority over exact reviewed bytes

Start from the exact challenger bundle ID emitted by the successful rehearsal. Rehydrate its bundle root and registry manifest, then run:

```bash
python scripts/derive_production_approval.py \
  --bundle-root <rehydrated-bundle-root> \
  --registry-root <rehydrated-registry-root> \
  --challenger-bundle-id <exact-challenger-bundle-id> \
  --approved-by <human-reviewer> \
  --note "Reviewed exact release rehearsal"
```

The command fails closed unless the source manifest is a byte-valid `challenger`, the target is explicit, and `--approved-by` is non-empty. It creates a new immutable manifest with:

- `authority=production_approved`
- `activation_eligible=true`
- the exact same artifact roles, relative paths, SHA-256 hashes, and byte counts as the challenger
- immutable provenance pointing back to the challenger bundle ID and human approval
- `automatic_promotion=false`

The production bundle gets a new bundle ID because authority and approval provenance are part of immutable identity. **This command does not move `champions.json`.**

## 2. Promote the exact approved bundle separately

After reviewing the derived production manifest and its provenance, activate that exact bundle with the existing registry operator:

```bash
python scripts/artifact_registry.py promote \
  --bundle-root <rehydrated-bundle-root> \
  --registry-root <rehydrated-registry-root> \
  --target preseason_multicontract_player_values_2026 \
  --bundle-id <production-approved-bundle-id> \
  --approved-by <human-reviewer> \
  --note "Activate reviewed Sept. 1 draft release"
```

Promotion re-loads the manifest and re-hashes every file before moving the champion pointer. A challenger bundle, a tampered bundle, an activation-ineligible bundle, a mismatched target, or a blank approver is rejected.

## Why the two steps are separate

A successful model benchmark, a successful 2026 rehearsal, human approval, and live activation are different claims. Keeping derivation and pointer movement separate prevents a CI success, artifact upload, or accidental command from silently becoming production authority.

The current league-specific caveats remain visible after approval:

- PPR season tails may influence decisions only under `qualified_distribution`.
- half-PPR season decisions remain `q50_only`.
- weekly median-game policy remains unvalidated and therefore provisional.
- kicker and DST remain `external_market_only` rather than model-scored positions.
- missing or stale current-state data can still make the live release gate provisional or blocked even when the projection bundle itself is production-approved.
