# Analyst Lens UX and published-score digest

**Base:** GameDay director/Sleeper diagnostics (PR #110). This is a research-friendly UI tranche, not a live NFL play provider.

## Navigation

Four primary workspaces: Draft Room, RedZone Companion, GameDay Lab and League OS. The other five surfaces remain reachable from an accessible **Explore** menu. Each retains its existing URL/route and model/data behavior. The global green "server-side model truth" indicator is replaced by a neutral source-aware label, so individual surface health can represent real failures accurately.

## Recorded GameDay Lab

- One contextual **Analyst Lens** card follows playback using only source-tagged frame events or currently observed geometry.
- A horizontal chapter strip jumps to **recorded source event timestamps**, replacing a redundant source-event sidebar panel.
- The selected player's **nearest opposite-side separation** is plotted with chart segments broken across source-frame gaps, missing player identities and missing team-side labels.
- The full historical proximity series is computed once per loaded play / selected player; the current marker moves during playback.
- The evidence label distinguishes `SOURCE_EVENT`, `OBSERVED_GEOMETRY`, and `EVIDENCE_GAP`. A nearest opponent is not a verified defensive assignment. A charted snap, pass, tackle or touchdown is a source annotation, not film alignment or grade.

## RedZone Companion

- Game score changes are exposed as published-source **revisions**, not reconstructed scoring drives or realtime play-by-play.
- Only newer, checksum-verified, nonstale source snapshots for the **same season/week and game identity** can create new update notes.
- Watchlist filtering still uses the user's local starred games; source updates are shown by default. No push messages are sent.
- The source freshness age updates while viewing the page.
- Public schedule polling remains **at most once every five minutes**, consistent with the backend throttle. A proper real-time commentator requires a legally usable, independently validated live PBP provider with possession, clock, play corrections and source timestamps.

## Reproduce

    cd apps/gemini-fantasy-console
    npm run build
    npm run test:field3d

Run repository browser smoke with headless Chromium. Compare desktop/mobile layout and reduced-motion behavior. For historical replay, import user-held source-validated replay JSON. For published RedZone score commentary, run the Python API and wait for a subsequent valid source snapshot; the initial snapshot is intentionally only a baseline.

## Non-goals / unresolved

This PR does not claim live 2026 3D tracking, player blocking/coverage classifications, Madden assets, seconds-level play-by-play, verified video alignment, public redistribution rights, or automatic model upgrades. It retains the open PR #110's underlying source and league integration contracts. Keep stacked until PR #110 merges and recomposition onto current main is verified.
