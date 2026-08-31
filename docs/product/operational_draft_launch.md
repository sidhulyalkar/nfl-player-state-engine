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

## 3. Declare and connect the real draft portfolio

The release artifact does not contain ownership or pick history. Actual-draft readiness therefore requires real platform snapshots, and aggregate readiness also needs to know how many leagues you intend to use.

The preferred path is the **Real Leagues** panel at the top of the Draft Room. First set the intended league count, then connect each real league by platform and numeric league ID. The aggregate Draft-Day Doctor behaves deliberately:

- intended count undeclared -> `PROVISIONAL` because portfolio completeness is unknown;
- fewer real leagues connected than declared -> aggregate `BLOCKED`;
- all intended real leagues connected -> the portfolio completeness check is `READY`, while any independent scientific caveats remain intact.

Tracked demo/example snapshots never count toward this contract and are excluded from aggregate actual-draft diagnosis.

The Product API exposes the same local onboarding boundary:

```text
GET /v1/draft/connections
PUT /v1/draft/connections/expectation
POST /v1/draft/connections
```

Example expectation payload:

```json
{"expected_league_count": 3}
```

Example Sleeper connection payload:

```json
{
  "platform": "sleeper",
  "league_id": "YOUR_NUMERIC_LEAGUE_ID",
  "season": 2026,
  "external_user_id": "OPTIONAL_SLEEPER_USER_ID",
  "include_free_agents": true
}
```

Example ESPN connection payload:

```json
{
  "platform": "espn",
  "league_id": "YOUR_NUMERIC_LEAGUE_ID",
  "season": 2026,
  "include_free_agents": true
}
```

ESPN cookie values are **not valid browser/API fields**. Private ESPN authentication is resolved only inside the Product API process from:

```bash
PSE_ESPN_S2=...
PSE_ESPN_SWID=...
```

The connection endpoint rejects unexpected fields with a sanitized error response so an accidentally supplied cookie value is not reflected back. The status endpoint exposes only the boolean `espn_private_auth_configured`, never either credential value.

Every platform import must pass the following validation before it can replace a snapshot:

- exact requested platform;
- exact requested league ID;
- exact requested season;
- at least one real roster and at least two teams;
- platform roster positions;
- platform scoring settings.

The normalized JSON snapshot is then atomically replaced. A failed import or failed validation preserves any previous valid snapshot. Real league JSON files and the local portfolio declaration are gitignored.

The older Sleeper CLI remains available as an operator fallback:

```bash
pse import-sleeper-league --league-id YOUR_LEAGUE_ID
```

Never create fake ownership or pick history simply to make readiness green.

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

Each stored market table is bound to metadata by SHA-256 and byte size. If a refresh is interrupted between data and metadata replacement, or the market bytes are later modified, readers reject the mixed/tampered pair and fall back to neutral timing. This is deliberately lighter-weight than champion authority but uses the same fail-closed instinct.

If the API key is absent, the refresh fails, the previous valid snapshot is preserved, and the Draft Room remains usable. Without true ADP the board falls back to neutral market timing rather than manufacturing a pick position. Market snapshots are full-confidence for six hours, then progressively lose timing confidence; after 24 hours they expire and no longer influence pick timing until refreshed. Freshness, staleness, and expiry are exposed in `/health` and the market-status endpoint.

## 5. Verify actual-draft readiness

```bash
export PSE_PROJECTION_SOURCE_MODE=champion
export PSE_ARTIFACT_REGISTRY_ROOT=artifacts/registry
export PSE_PRODUCTION_BUNDLE_ROOT=artifacts/production/preseason_2026
export PSE_PROJECTION_CHAMPION_TARGET=preseason_multicontract_player_values_2026
python scripts/check_draft_checkout.py --strict-data
```

Strict preflight re-resolves and re-verifies the same champion used by the Product API. A schema-valid development path is not sufficient. Live ADP is a quality enhancement rather than a model-authority blocker.

## 6. Run the Draft-Day Doctor

The strict checkout gate answers whether the required release artifacts exist. The Draft-Day Doctor answers the more useful operator question: **can this exact installed system safely help with these exact leagues right now?**

Run it before the first draft and again after any source or league refresh:

```bash
python scripts/draft_day_doctor.py
```

For one league:

```bash
python scripts/draft_day_doctor.py --league-id YOUR_LEAGUE_ID
```

For machine-readable automation:

```bash
python scripts/draft_day_doctor.py --json
```

Once the Product API is running, the same diagnosis is available at:

```text
GET /v1/draft/doctor
GET /v1/draft/doctor?league_id=YOUR_LEAGUE_ID
```

The aggregate endpoint composes:

- exact production champion mode, authority, integrity, and projection source cutoff;
- NFL Hub authority, freshness, required-source health, and market identity coverage;
- declared real-league portfolio completeness;
- real league snapshot/roster presence and snapshot age;
- exact scoring-contract selection and core QB/RB/WR/TE readiness;
- K/DST `external_market_only` availability when a league actually requires those slots;
- median-game and unsupported scoring-policy caveats;
- live ADP availability, freshness, integrity, and league-format authority.

Verdicts mean:

- `READY`: no known operational or scientific caveat in the checked surface;
- `PROVISIONAL`: core draft recommendations remain usable, but at least one explicitly bounded caveat is active;
- `BLOCKED`: at least one hard authority/data contract is violated. Do not use the affected draft board until its remediation is completed.

Portfolio incompleteness blocks the **aggregate** readiness badge but does not revoke core authority from an already connected, individually healthy league. Missing, stale, or format-proxy ADP is deliberately `PROVISIONAL`, not a hard model blocker. Missing required K/DST support, invalid champion authority, stale hard-gated NFL state, or broken core scoring-contract readiness are `BLOCKED`.

The doctor is diagnostic only: it does not refresh sources, rewrite league state, approve/promote artifacts, or move champion pointers.

## 7. Launch the Draft War Room

The default Docker Compose stack is production-authority aware and includes the optional ESPN adapter:

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

- live ADP unavailable, stale, expired, or format-proxy-only;
- K/DST `external_market_only` authority;
- unvalidated median-game policy;
- optional/degraded NFL Hub source families.

A production-approved champion can therefore still support a **PROVISIONAL** league verdict. That is expected and preferable to manufacturing certainty on the pick clock.
