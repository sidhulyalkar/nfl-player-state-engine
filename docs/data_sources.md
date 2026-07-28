# Data Sources

## Core football data

The primary source is nflverse through the `nflreadpy` Python package. Core tables are player stats, schedules, rosters, weekly rosters, and depth charts.

## Optional football data

- Snap counts
- Participation
- Next Gen Stats weekly aggregates
- FTN charting

Optional sources can have narrower historical coverage, delayed updates, or separate attribution terms. The loader treats them as non-blocking.

## Availability and news

The v0.3 repository includes a structured availability schema and manual import template. A production feed should provide clear usage rights, timestamps, corrections, stable player identifiers, source type, and reliability. Official NFL/team injury reports and transactions should be the first production layer.

Never scrape a source merely because it is technically possible.

## Public player context

Supported connector scaffolds:

- X official API v2
- Meta Threads public profile-post API
- Instagram Business Discovery for eligible public professional accounts
- TikTok Research API for approved qualifying research
- RSS feeds
- Explicit robots-allowed static public pages
- JavaScript-rendered pages genuinely available to clean unauthenticated browsers

No connector attempts to access private profiles, direct messages, follower identity lists, deleted content, login-only pages, or access-control bypasses. Rendered collection stops on password forms, CAPTCHAs, and access challenges.

## Market data

No automated odds provider is included. Market snapshots should be imported manually or through a properly licensed API. Store the exact capture time and price. Retrospectively using a closing line as though it were available earlier invalidates the experiment.
