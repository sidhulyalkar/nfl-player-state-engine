# Injury, News, and Public Player Intelligence

## Status

Scaffolded, disabled by default, and intentionally excluded from the frozen numerical benchmark.

## Goal

Create timestamped evidence streams that may improve participation, workload, role-change, and uncertainty estimates after the numerical model is stable.

## Data layers

### Availability evidence

`AvailabilityEvidence` accepts official injury reports, practice participation, inactive lists, team transactions, press conferences, licensed news, and manual research annotations. `pse build-availability` converts records into conservative availability snapshots.

### Public documents

`pse collect-intelligence` supports:

- official X API v2;
- official Threads API;
- Instagram Business Discovery for eligible professional accounts;
- approved TikTok Research API;
- RSS feeds;
- `public_web` static pages;
- `public_browser` JavaScript-rendered pages that are public without authentication.

The browser collector starts with an empty profile, honors robots.txt, blocks private-network requests, and stops on login, CAPTCHA, or challenge pages. It does not import cookies, evade controls, or reverse-engineer private endpoints.

### Persona snapshots

`pse build-personas` extracts observable public football-context signals:

- training emphasis;
- recovery emphasis;
- competitive language;
- team orientation;
- leadership language;
- matchup specificity;
- role expectations;
- media visibility;
- commercial-content share.

These are weak, noisy contextual features. They are not diagnoses, stable personality labels, or direct measurements of motivation.

## Example workflow

```bash
cp examples/player_sources_template.csv data/external/intelligence/player_sources.csv
python -m pip install -e ".[browser]"
playwright install chromium

pse collect-intelligence \
  --registry data/external/intelligence/player_sources.csv \
  --output data/external/intelligence/documents.jsonl

pse build-personas \
  --documents data/external/intelligence/documents.jsonl \
  --output data/processed/persona_features.parquet \
  --evidence artifacts/reports/persona_evidence.json

pse attach-intelligence \
  --features data/processed/weekly_features_2020_2025.parquet \
  --intelligence data/processed/persona_features.parquet \
  --output data/processed/weekly_features_with_persona.parquet
```

The point-in-time join chooses the latest snapshot known before kickoff, with an additional safety lag.

## Recommended ablation order

1. Official inactive/game status.
2. Practice participation trend.
3. Transactions and depth-chart state.
4. Snap share, route participation, and team volume.
5. Licensed news role extraction.
6. Player-authored recovery and role language.
7. Remaining public-context features.

Do not combine all intelligence in the first experiment. If the bundle improves, the causative ingredient will otherwise vanish into feature soup.

## Modeling safeguards

- Keep raw text out of the tabular baseline until a registered text experiment.
- Prefer structured evidence before opaque embeddings.
- Down-weight advertisements and duplicated content.
- Require source diversity and evidence strength.
- Widen uncertainty before shifting the median when evidence is ambiguous.
- Run shuffled-player and shifted-time negative controls.
- Compare public context against official availability and objective usage features.
