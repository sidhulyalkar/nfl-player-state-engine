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

Only after those checks does it derive a separate `production_approved` manifest over unchanged bytes and move the local champion pointer. Re-running the same reviewed challenger is idempotent. If the target already points to a different champion, the command fails **before copying candidate bytes**; replacing an existing champion requires a separately designed and reviewed storage/rollback migration rather than an in-place overwrite.

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

## 4. Refresh the live draft market

True ADP is a current **market-timing overlay**, not part of the immutable football projection champion. This separation is intentional: the market can move during draft week without retraining or reapproving the preseason model.

When FantasyPros API access is configured:

```bash
export PSE_FANTASYPROS_API_KEY=<YOUR_KEY>
python scripts/refresh_live_adp.py --season 2026
```

The Product API exposes the same operations:

```text
GET  /v1/draft/market/status
POST /v1/draft/market/refresh?season=2026
GET  /v1/leagues/{league_id}/draft/market
```

The refresh collects four point-in-time market views:

```text
PPR  / ALL
PPR  / OP
HALF / ALL
HALF / OP
```

`ALL` supplies the ordinary 1QB timing context. `OP` supplies a superflex-style market proxy for multi-QB rooms. It is **not** labeled as exact 2QB authority. The API also does not certify an exact team count, so an 8-team 2QB league receives a deliberately reduced format-confidence score and a wider timing-uncertainty proxy.

For `type=ADP`, the integration requires an explicit average-position field such as `rank_ave`. It refuses to substitute the ordinal `rank_ecr` field as ADP. Likewise, FantasyPros `rank_std` is not represented as empirical pick-position standard deviation. The live board derives a conservative timing uncertainty and labels that provenance explicitly.

If the API key is absent, the refresh fails, the previous valid snapshot is preserved, and the Draft Room remains usable. Without true ADP the board falls back to neutral market timing rather than manufacturing a pick position. Market snapshots older than six hours are reported as stale in `/health` and the market-status endpoint.

## 5. Verify actual-draft readiness

```bash
export PSE_PROJECTION_SOURCE_MODE=champion
export PSE_ARTIFACT_REGISTRY_ROOT=artifacts/registry
export PSE_PRODUCTION_BUNDLE_ROOT=artifacts/production/preseason_2026
export PSE_PROJECTION_CHAMPION_TARGET=preseason_multicontract_player_values_2026
python scripts/check_draft_checkout.py --strict-data
```

Strict preflight re-resolves and re-verifies the same champion used by the Product API. A schema-valid development path is not sufficient. Live ADP is a quality enhancement rather than a model-authority blocker.

## 6. Launch the Draft War Room

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

`/health` also surfaces the current draft-market status independently from champion health.

Open:

```text
http://localhost:3000/?workspace=draft
```

Docker Compose waits for the verified API health check before starting the frontend. If the champion pointer or bytes are invalid, the API fails closed instead of falling back to `PSE_PROJECTIONS_PATH`.

## Known provisional boundaries

Promotion changes artifact authority, not scientific evidence. Continue to surface known limitations honestly, including any current release flags for:

- live ADP unavailable, stale, or format-proxy-only;
- K/DST `external_market_only` authority;
- unvalidated median-game policy;
- optional/degraded NFL Hub source families.

A production-approved champion can therefore still support a **PROVISIONAL** league verdict. That is expected and preferable to manufacturing certainty on the pick clock.
