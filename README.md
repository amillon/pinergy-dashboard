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

`public/` is a build artifact — **never committed**. `data/pinergy_data.json` is
regenerated at each run; only the two history files below are committed.

## Hourly history

`/api/levelpayusage/` returns half-hourly kWh for the **last 7 days only**, so
`fetch_pinergy.py` appends it to `data/history_halfhourly.ndjson` (one line per
day: `{date, kwh: [48 floats 00:00→23:30], fetched_at}`), committed by the
daily workflow. A day is overwritten if it reappears (Pinergy can revise it).
If a run is missed for more than 6 days, the lost days can't be recovered and
the job logs a `::warning::half-hourly gap`. The dashboard excludes a day
still in progress at fetch time.

Views: calendar + day×hour heatmaps (tab *Suivi*), peak-hour analysis
(tab *Optimisation*: peak hour, top-3 share, evening share, standing load,
hour bars with min/max, weekday×hour heatmap once each weekday has ≥ 2 samples).

Tests (offline): `python3 -m unittest discover tests`.

## Data & privacy

Only `balance`, `usage` (day/week/month), `compare` and the half-hourly `levelpayusage` are fetched.
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
