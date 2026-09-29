# S&P 500 Stock Screener

A glass-styled screener for every S&P 500 constituent: live-ish quotes, 30-day
sparklines, a detailed price chart, valuation metrics, expected-vs-actual EPS for
the last four quarters and four fiscal years plus next-quarter and next-year
consensus, and a configurable daily price-move screen. Companies are organised by
GICS sector, industry group and sub-industry, the same taxonomy sell-side research
coverage uses.

It is a static site: no server, no API keys in the browser. A Python pipeline
produces JSON; the page reads it. GitHub Actions refreshes the data every weekday
after the close and deploys to GitHub Pages.

```
app/                    the site (open index.html, or deploy the folder as-is)
  index.html            markup
  styles.css            design tokens, light + dark themes, laptop / iPad / iPhone layouts
  charts.js             SVG sparkline, price chart with crosshair, earnings dots
  app.js                state, filtering, sorting, screener, detail sheet
  data/stocks.json      the universe (503 rows) - generated
  data/alerts.json      the daily screen results - generated
  data/history/*.json   per-sector price history + news bundles, lazy-loaded - generated
pipeline/
  fetch_data.py         Wikipedia constituents + Yahoo Finance (yfinance) -> app/data
  screen.py             applies screener.config.json -> app/data/alerts.json
  gics.py               sub-industry -> industry group mapping
  build_artifact.py     bundles app/ into dist/index.html for publishing as a claude.ai Artifact
screener.config.json    the daily screens: window, threshold, direction
.github/workflows/daily.yml   weekday refresh + Pages deploy
```

## Run it locally

```bash
pip install -r pipeline/requirements.txt
python pipeline/fetch_data.py      # ~3 minutes for all 503 tickers
python pipeline/screen.py
python -m http.server 8000 --directory app   # then open http://localhost:8000
```

`fetch_data.py --limit 20` fetches a subset while developing.

## Daily screen rules

Edit `screener.config.json`. Each rule has a `window` (`1d`, `1w`, `1m`, `3m`,
`6m`, `1y`), a `threshold_pct` (positive magnitude) and a `direction` (`up`,
`down`, `either`). The workflow writes the hits to `app/data/alerts.json` each
run, and the Screener tab shows the same rules as one-tap presets whose counts
are computed live, so you can also tune the threshold and time frame in the UI
without editing anything.

## Refreshing

The refresh button in the top bar re-reads every data file (bypassing caches)
and redraws, so on GitHub Pages it picks up the daily job's output without a
page reload. Generating new data means running the pipeline: the scheduled
workflow does that on weekdays, `workflow_dispatch` runs it on demand, and the
"S&P 500 Screener: refresh data" Routine in claude.ai runs it and republishes
the artifact.

## Deploy

1. In the repository settings, under Pages, set the source to **GitHub Actions**.
2. Run the "Daily data refresh" workflow once from the Actions tab (or wait for
   the 22:15 UTC weekday schedule). It commits fresh data and deploys `app/`.

## Data notes

- Prices, market cap, valuation ratios, EPS history, consensus and headlines come from
  Yahoo Finance via `yfinance`. Quotes are the latest available at run time
  (delayed during market hours).
- "Trading since" is the first trade date Yahoo has on file, which for very old
  listings is the start of its data rather than the true IPO.
- Quarterly EPS is the adjusted figure companies are measured against. Annual
  EPS is the sum of the four reported quarters so it sits on the same basis as
  the consensus; a year without four quarters on file falls back to GAAP diluted
  EPS and is labelled as such in the chart tooltip.
- Fiscal quarter labels follow each company's fiscal year end (Apple's Q4 ends
  in September, Nvidia's fiscal 2027 began in February 2026).
