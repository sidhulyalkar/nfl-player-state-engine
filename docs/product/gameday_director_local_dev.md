# GameDay Director and local API diagnostics (development tranche)

This change separates **backend reliability** from **replay research visualization**.

## Local setup

From the **repository root**:

    python3.11 -m venv .venv
    .venv/bin/python -m pip install -e '.[dev,api,espn,intelligence]'
    npm ci --include=optional
    npm run dev:full

This command launches the separately installed Python operational API at
`http://127.0.0.1:8000` plus the Node/React frontend on port 3000. It uses
the current `.venv` instead of silently using an arbitrary global Python.
Ctrl-C tears down the owned Python process. Existing healthy Python API
processes are reused. If another app occupies port 8000, resolve that
conflict instead of trying to force an import through a wrong service.

**Diagnostic checks:**

    curl -fsS http://127.0.0.1:8000/health
    curl -s http://127.0.0.1:3000/api/pse/diagnostics

The second endpoint reports Python API reachability and source-integrity
status. It does not pretend the Node server itself imports Sleeper leagues.
If the proxy cannot reach Python, it returns a stable
`PSE_UPSTREAM_OFFLINE` or `PSE_UPSTREAM_TIMEOUT` code with a startup
instruction; it does not leak upstream exception text or credentials.

The Sleeper connection's optional user field can be a username or
user ID. Within a fetched league the adapter resolves an exact case-folded
`username` against the fetched membership list, and only maps the roster
if the match is unique. An unknown username never selects an arbitrary
roster. The platform API, source network, 2026 league existence, and
production champion artifacts are separate validation requirements.
Never treat a successful proxy health check as a confirmed league import.

## Replay theater

The GameDay Lab field fills most of its workspace and has a collapsible
analysis rail. Broadcast mode offers an opt-in-by-default moving camera,
with a manual override on drag/zoom and an explicit **Resume auto camera**
button. Tactical All-22 and overhead remain wide, static views.

The director only follows valid recorded ball x/y, an explicitly selected
recorded player, or the centroid of visible recorded players. Frame gaps
**freeze** the camera, not interpolate synthetic movement. Source event tags
adjust zoom and drive a research-only commentary card. A nearest-opponent
distance is geometry, **not** a coverage assignment or attribution of good
blocking. Synthetic tutorials are labelled synthetic throughout.

The 3D scene uses original generic football figures and decorative
stadium apron geometry. No Madden, NFL player likeness, uniforms, mocap,
broadcast footage, or proprietary assets are imported. It does not
infer facing/orientation, ball height, offensive scheme or win probability.

## Tests

    cd apps/gemini-fantasy-console
    npm run build
    npm run test:field3d

    cd ../..
    python -m pytest tests/product/test_sleeper_importer.py

Also run the existing browser smoke for the native 3D/SVG fallback under a
WebGL2-capable headless browser.

## Remaining gates

- Independently connect the exact desired Sleeper league from a live,
  reachable Python API, without logging credentials or private roster data
  into public test artifacts.
- Visual review on Safari/Firefox and macOS Retina at small and wide sizes;
  check frame time, reduced-motion settings and camera-control accessibility.
- Film-aligned event/coverage/blocking/tackle classification requires lawful
  video and measured labeling quality before any explanatory conclusions.
