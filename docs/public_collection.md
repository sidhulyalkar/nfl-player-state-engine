# Public-content collection boundaries

## Implemented collectors

The intelligence package now provides two non-authenticated webpage modes:

- `public_web`: static HTML fetch for simple pages;
- `public_browser`: Playwright rendering for JavaScript-driven pages that are genuinely public without authentication.

Both modes:

- honor `robots.txt`;
- use an identifying user agent;
- rate-limit requests;
- reject localhost, private IPs, internal hostnames, credentials in URLs, and unsafe redirects;
- stop on password forms, login gates, CAPTCHAs, and access challenges;
- retain canonical URL, timestamps, content hash, collection time, and extractor metadata;
- collect visible public text rather than private endpoints or session data.

Install browser support with:

```bash
python -m pip install -e ".[browser]"
playwright install chromium
```

Then add a registry row such as:

```csv
00-0031234,Example Player,public_browser,,https://example.com/public-profile,false,Public without authentication; robots must allow
```

## What is not implemented

The repository does not bypass login walls, reuse stolen or exported cookies, solve CAPTCHAs, rotate proxies to evade limits, impersonate mobile clients, reverse-engineer private APIs, or scrape private/deleted content.

A person being a public figure does not make every platform delivery mechanism unrestricted. The collector may ingest content that the publisher actually serves to a clean, unauthenticated browser. When the platform returns a login or challenge page, collection stops.

## Recommended source priority

1. Official NFL and team injury reports, transactions, press conferences, and depth charts.
2. Licensed news and RSS feeds.
3. Official platform APIs.
4. Athlete-controlled websites, newsletters, podcasts, and public interviews.
5. Static or rendered public pages allowed by robots.txt.

This ordering maximizes timestamp quality and minimizes the chance that fragile web presentation changes become model features.
