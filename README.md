# Pinergy Smart — consumption dashboard

A single-page, no-backend dashboard for a Pinergy Smart prepaid electricity
account, refreshed daily and published on GitHub Pages via GitHub Actions.

## Architecture

```
fetch_pinergy.py   → calls the Pinergy API (via pypinergy), writes data/pinergy_data.json
build_dashboard.py → injects that JSON into template.html, writes public/index.html
template.html      → static HTML/CSS/JS; all KPIs and charts are computed client-side
                      from window.PINERGY_DATA (Plotly, Converteo branding)
.github/workflows/refresh.yml → runs the two scripts daily and deploys public/ to Pages
```

`data/` and `public/` are build artifacts — **never committed**. Each workflow
run fetches fresh data, builds the page, and uploads it as a Pages artifact;
nothing lands in git history.

## Data & privacy

Only `balance`, `usage` (day/week/month) and `compare` are fetched.
`active_topups` is not requested. The Pinergy endpoints used here never
return account-holder identity, house, or payment-card data (those only
exist in the login response, which this script never touches) — the
exported JSON contains no PII by construction.

## Setup

1. Create two repository secrets (Settings → Secrets and variables → Actions):
   - `PINERGY_EMAIL`
   - `PINERGY_PASSWORD`
2. Enable GitHub Pages with source **GitHub Actions** (Settings → Pages).
3. The `refresh` workflow runs daily at 06:30 UTC, or on demand via
   **Actions → Refresh Pinergy dashboard → Run workflow**.

## Local run

```bash
pip install -r requirements.txt

# credentials via env vars, or a ~/.pinergy.env file (KEY=VALUE, local only)
python fetch_pinergy.py
python build_dashboard.py

open public/index.html
```

## Tariff constants

The "Optimisation" section's fixed/variable rate split
(`TARIFF.fixedPerDay`, `TARIFF.variablePerKwh`) and market benchmark
(`TARIFF.marketBestRate`, `TARIFF.marketBestFixedAnnual`) are hardcoded
constants in `template.html` — they were reconstituted by regression on
observed billing, not derived from the API. Update them there if the plan
or the market benchmark changes.
