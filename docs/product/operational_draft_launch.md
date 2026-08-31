# Operational 2026 draft launch

This is the shortest supported path from a reviewed preseason GitHub Actions artifact to the local Draft War Room.

## 1. Download the reviewed workflow artifact

Download the ZIP produced by the successful `2026 multicontract preseason candidate rehearsal` run you actually reviewed. Do not substitute an older candidate because its filenames look similar.

The ZIP must contain:

- the challenger bundle manifest;
- the exact immutable challenger files;
- the three-league rehearsal report;
- the current NFL Hub snapshot;
- the current K/DST market snapshot.

## 2. Materialize and activate one exact challenger

From the repository root:

```bash
python scripts/materialize_preseason_production.py \
  /path/to/preseason-workflow-artifact.zip \
  --approve-bundle-id <EXACT_REVIEWED_CHALLENGER_BUNDLE_ID> \
  --approved-by <YOUR_GITHUB_LOGIN>
```

The command intentionally requires the exact content-addressed challenger bundle ID. That argument is the operator's explicit approval of those reviewed bytes.

The materializer then fails closed unless all of the following hold:

- the rehearsal is promotion eligible;
- the only hard pre-approval blocker is `PROJECTION_BUNDLE_NOT_PRODUCTION_APPROVED`;
- all three saved league profiles are present;
- all three have green core readiness;
- the two half-PPR roster constructions share one scoring-model contract;
- all required artifact roles are present;
- every extracted file matches the challenger manifest's SHA-256 and byte size;
- the challenger target is exactly `preseason_multicontract_player_values_2026`.

Only after those checks does it derive a separate `production_approved` manifest over unchanged bytes and move the local champion pointer. Re-running the same reviewed challenger is idempotent. Replacing a different existing champion requires the explicit `--replace-existing-champion` flag.

The default local materialization layout is:

```text
artifacts/production/preseason_2026/
artifacts/registry/bundles/
artifacts/registry/champions.json
data/product/nfl_hub/current.json
data/product/special_teams_market/current.json
artifacts/release_reports/preseason_2026_activation.json
```

## 3. Import or sync your real leagues

The production model can be activated without inventing league state. Actual-draft readiness still requires real league snapshots.

Sleeper example:

```bash
pse import-sleeper-league --league-id YOUR_LEAGUE_ID
```

For other platforms, use the maintained importer or explicit CSV/manual boundary. Never create fake ownership or pick history simply to make strict preflight green.

## 4. Verify actual-draft readiness

```bash
export PSE_PROJECTION_SOURCE_MODE=champion
export PSE_ARTIFACT_REGISTRY_ROOT=artifacts/registry
export PSE_PRODUCTION_BUNDLE_ROOT=artifacts/production/preseason_2026
export PSE_PROJECTION_CHAMPION_TARGET=preseason_multicontract_player_values_2026
python scripts/check_draft_checkout.py --strict-data
```

Strict preflight re-resolves and re-verifies the same champion used by the Product API. A schema-valid development path is not sufficient.

## 5. Launch the Draft War Room

The default Docker Compose stack is production-authority aware:

```bash
docker compose up --build pse-api fantasy-console
```

The API health check must report:

```text
projection_source_mode=champion
projection_authority=production_approved
projection_integrity_verified=true
projection_target=preseason_multicontract_player_values_2026
```

Open:

```text
http://localhost:3000/?workspace=draft
```

Docker Compose waits for the verified API health check before starting the frontend. If the champion pointer or bytes are invalid, the API fails closed instead of falling back to `PSE_PROJECTIONS_PATH`.

## Known provisional boundaries

Promotion changes artifact authority, not scientific evidence. Continue to surface known limitations honestly, including any current release flags for:

- true ADP availability;
- K/DST `external_market_only` authority;
- unvalidated median-game policy;
- optional/degraded NFL Hub source families.

A production-approved champion can therefore still support a **PROVISIONAL** league verdict. That is expected and preferable to manufacturing certainty on the pick clock.
