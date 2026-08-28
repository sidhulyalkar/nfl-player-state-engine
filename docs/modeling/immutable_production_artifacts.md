# Immutable production artifacts

## Problem

A successful model run is not the same thing as a durable production model.

GitHub Actions caches are useful compute accelerators and workflow artifacts are useful review transports, but neither is the authority for which exact model and projection bytes the product is allowed to serve. Cache keys can disappear, retention windows expire, and filesystem paths do not prove content identity.

The production contract therefore separates three things:

1. **immutable bundle**: content-addressed model, projections, metrics, calibration and provenance files;
2. **transport/storage**: local disk, Actions artifact, object store or another durable backend;
3. **champion pointer**: the small mutable record that says which verified bundle is currently active for a target.

Only the third item is supposed to move.

## Bundle identity

`player_state_engine.learning.artifact_registry` hashes every registered file with SHA-256 and creates a bundle ID from canonical JSON containing:

- artifact type;
- authority;
- activation eligibility;
- model ID and target when applicable;
- code SHA;
- config SHA-256;
- source cutoff;
- role → relative path → bytes → SHA-256 records;
- explicit metadata.

Filesystem modification times and manifest write time do not affect identity. The same bytes and scientific identity produce the same bundle ID; changed bytes produce a different bundle ID.

Every file must live below the declared bundle root. This keeps manifests relocatable and prevents a manifest from quietly depending on an unrelated machine-local path.

## Authority

Bundles have one of three authority states:

- `research_only`
- `challenger`
- `production_approved`

`activation_eligible=true` is legal only for `production_approved` bundles.

This is deliberately separate from historical benchmark success. A benchmark may make a challenger eligible for manual review without creating a production-approved bundle.

## Promotion

Promotion is a pointer update, never a rewrite of the bundle.

The promotion operator requires:

- an existing immutable manifest;
- a matching bundle ID;
- fresh SHA-256 and byte-size verification of every file;
- `authority=production_approved`;
- `activation_eligible=true`;
- matching target when the manifest declares one;
- a non-empty `approved_by` identity.

There is no automatic-promotion code path.

After promotion, serving should resolve the champion pointer and verify the bundle again. If any file has changed after approval, resolution fails closed.

## Operator

Register a bundle:

```bash
python scripts/artifact_registry.py register \
  --bundle-root artifacts/production/2026-w01 \
  --registry-root artifacts/registry \
  --artifact-type weekly_projection \
  --authority challenger \
  --model-id weekly-ppr-2026-w01 \
  --target fantasy_points_ppr \
  --code-sha "$GITHUB_SHA" \
  --config-sha256 "$CONFIG_SHA" \
  --source-cutoff-utc 2026-09-08T20:00:00+00:00 \
  --file model=artifacts/production/2026-w01/model.joblib \
  --file projections=artifacts/production/2026-w01/projections.parquet
```

Verify later:

```bash
python scripts/artifact_registry.py verify \
  --bundle-root artifacts/production/2026-w01 \
  --registry-root artifacts/registry \
  --bundle-id BUNDLE_ID
```

Manual promotion, after a separate evidence/approval step has created an activation-eligible production-approved bundle:

```bash
python scripts/artifact_registry.py promote \
  --bundle-root artifacts/production/2026-w01 \
  --registry-root artifacts/registry \
  --target fantasy_points_ppr \
  --bundle-id BUNDLE_ID \
  --approved-by human-reviewer \
  --note "Frozen gate and prospective review passed"
```

Resolve a champion:

```bash
python scripts/artifact_registry.py resolve \
  --bundle-root artifacts/production/2026-w01 \
  --registry-root artifacts/registry \
  --target fantasy_points_ppr
```

## Storage boundary

This PR intentionally does not choose a cloud vendor.

The local contract is the authoritative format. A later storage adapter can upload the immutable bundle directory and registry manifests to S3, GCS, GitHub Release assets, or another durable object store. The storage backend must preserve bytes; it does not decide model authority.

A workflow cache may continue to hold training downloads and candidate state for speed, but cache restoration must never be interpreted as production approval.

## Product integration sequence

Before the Draft Room consumes a production projection artifact:

1. resolve the champion pointer for the relevant model authority;
2. verify every content hash;
3. verify source cutoff and code/config provenance;
4. materialize projection metadata from the verified manifest;
5. run league readiness/actionability gates;
6. only then expose a recommendation as qualified.

This makes `READY` traceable all the way down to exact model and projection bytes rather than merely to a path that happened to exist on disk.
