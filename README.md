# macro_watch

A toolkit for **weekly cross-asset macro market analysis**. It ingests, aligns, computes, and
visualizes macro-financial data so you can read the week's rates, equity, and commodity regimes
at a glance — with a focus on the US Treasury and JGB curves.

The **primary display is a browser dashboard** (Vite + TypeScript + Observable Plot) — see
[Web view](#web-view). Python owns all ingestion and analytics and writes a JSON snapshot that the
front-end renders.

### 🔗 Live dashboard → **https://kfujie.github.io/macro_watch/**

Published to GitHub Pages and **auto-refreshed daily** (23:00 UTC, after the US cash close) via
[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) — no setup needed to just browse the
latest read. To run it locally instead, see [Web view](#web-view).

## Package layout

```text
macro_watch/
├── __init__.py
├── data_loader.py      # MoF (JGB), FRED, Yahoo ingestion + Parquet caching
├── analytics.py        # curves, real rates, rolling correlations, z-scores
├── sectors.py          # S&P 500 / Nikkei 225 sector attribution (ETF proxies)
└── web_export.py       # dump the panel + analytics to web/public/data.json

web/                    # experimental Vite + TypeScript + Observable Plot dashboard
```

Python is the single source of truth for ingestion and analytics; the web front-end does **no**
computation — `web_export.py` writes one `data.json` that the TypeScript app renders.

## Data sources

| Block       | Series                                                      | Source |
|-------------|-------------------------------------------------------------|--------|
| JP rates    | JGB 2Y / 5Y / 10Y / 20Y / 30Y / 40Y                         | MoF Japan (Shift-JIS CSV, Japanese-era dates) |
| US rates    | UST 2Y / 3Y / 5Y / 7Y / 10Y / 20Y / 30Y, T10YIE (10Y breakeven) | FRED (keyless `fredgraph.csv`) |
| Commodities | WTI (`DCOILWTICO`), Gold                                    | FRED / Yahoo `GC=F` |
| FX          | USD/JPY (`JPY=X`), DXY (`DX-Y.NYB`), EUR/USD, EUR/JPY       | Yahoo Finance |
| Equities    | `^GSPC`, `^IXIC`, `^N225`, `^TOPX`                          | Yahoo Finance (adjusted close) |
| Sector ETFs | 11 SPDR Select Sector (US, e.g. `XLK`), 17 NEXT FUNDS TOPIX-17 (JP, `1617.T`–`1633.T`) | Yahoo Finance (sector-attribution proxies) |

**Source notes**
- The spec's JGB URL (`jgbcm.csv`) carries only the current month; it is combined with the
  historical `data/jgbcm_all.csv` (identical schema) so rolling statistics have full lookback.
- FRED's London Gold Fix (`GOLDAMGBD228NLBM`) was discontinued and de-listed (HTTP 404), so gold
  is sourced from Yahoo COMEX front-month `GC=F`.
- `^TOPX` has no free Yahoo history; the TOPIX column is retained but resolves to `NaN` and is
  handled gracefully (excluded from the heatmap).

## Analytics

**Cross-asset**
- **US real yield** — `US10Y_nominal − US10Y_BEI`.
- **Momentum z-scores** — 1-week (5d) and 4-week (20d) moves normalized by rolling 90-day daily
  volatility (`σ_daily · √horizon`); log returns for prices, absolute diffs for yields.
- **Rolling correlations** — 30d / 60d Pearson for Real Yield↔Gold, WTI↔BEI, S&P 500↔US10Y.

**Rates deep-dive (US Treasury & JGB)** — `analytics.curve_metrics / rates_snapshot / tenor_snapshot / curve_pca`
- **Slopes** — every standard pair in bps (US 2s5s/2s10s/5s10s/5s30s/10s30s/2s30s; JGB
  2s10s/5s10s/10s20s/10s30s/20s30s/2s30s/5s30s).
- **Butterflies** — *tenor-weighted* curvature (belly richness vs the wings' yield/tenor
  interpolation), belly-cheap positive, correct sign for unevenly-spaced flies like 5s10s20s
  (US 2s5s10s/5s7s10s/5s10s30s/10s20s30s; JGB 2s5s10s/5s10s20s/10s20s30s/20s30s40s).
  `fly_weighting="equal"` gives the simple 2:1:1 fly.
- **Snapshots** — outright tenor and curve tables with WoW/1M moves (bps), momentum z-score
  (`Z_1W`), level richness z-score (`Z_level`), and trailing-year percentile.
- **Curve PCA** — level/slope/curvature decomposition (sign-normalized PC1/PC2/PC3) with
  3-factor **rich/cheap** residuals per tenor (+ cheap / − rich).

**FX — dollar & yen** — `analytics.fx_snapshot / rate_differential / fx_rate_fairvalue`
- **FX momentum** — USD/JPY, DXY (primary), EUR/USD, EUR/JPY with WoW/1M % and z-scores.
- **Rate differential** — US−JP nominal yield gap (bp), the dominant USD/JPY driver.
- **Rate-differential fair value** — OLS of USD/JPY on the US−JP differential (~5y default);
  residual = how far the yen trades from its rate-implied level (+ = yen cheap). Beta is
  regime-dependent (positive structurally, can invert short-term) — check `r2`/`beta`.

**Equities — sector attribution** — `sectors.build_equities`
- Decomposes the S&P 500 and Nikkei 225 moves into **sector contributions**
  (`contribution = sector weight × sector return`), so the bars approximately sum to the index
  return. Sector proxies are liquid ETFs from Yahoo: the 11 **SPDR Select Sector** ETFs (US, GICS)
  and the 17 **NEXT FUNDS TOPIX-17** ETFs (Japan; the N225 has no free sector decomposition, so
  TOPIX-17 is the Japan sector backdrop). Index weights are a documented **static approximation**
  (no clean free live feed), so the residual vs the actual index move is surfaced for honesty.
- Sector ETF prices are cached **separately** (`data_cache/sector_panel.parquet`) and never enter
  the canonical panel's `CANONICAL_COLUMNS`.

These analytics are rendered by the browser dashboard — see [Web view](#web-view).

## Setup

```bash
uv sync   # install Python dependencies into .venv
```

### Web view

The primary display. The live build is hosted at **https://kfujie.github.io/macro_watch/**
(auto-refreshed daily); the steps below are for running it locally. The pipeline is decoupled:
Python writes a JSON snapshot, TypeScript renders it — the front-end does no computation.

```text
macro_watch (Python)            web/ (TypeScript)
  data_loader + analytics  →  web_export.py  →  web/public/data.json  →  Plot charts + tables
  + sectors
```

```bash
# 1. Generate the data snapshot (from the repo root):
uv run python -m macro_watch.web_export            # uses the Parquet caches
uv run python -m macro_watch.web_export --refresh  # re-fetch all sources first

# 2. Run the dev server (from web/):
cd web && npm install   # first time only
npm run dev             # http://localhost:5173
```

The page shows a **static snapshot**: when the numbers change, re-run `web_export` and reload.
`data.json` is git-ignored (regenerated from sources), so run step 1 once after a fresh clone.
It renders rates (curve, slopes, **butterflies**, PCA), FX, equity **sector attribution**
(S&P 500 / Nikkei 225), and the cross-asset z-score row. See [`web/README.md`](web/README.md) for
the front-end layout.

### Programmatic use

```python
from macro_watch.data_loader import MacroDataLoader
from macro_watch import analytics

panel = MacroDataLoader().load(refresh=True)        # fetch + cache (Parquet)
rates = analytics.rates_snapshot(panel, "US")       # slopes & flies: WoW/1M, z-scores
corr = analytics.cross_asset_correlations(panel)    # strongest cross-asset pairs
```

The loader degrades gracefully: any single source that fails is skipped (with a warning) and its
columns are emitted as `NaN`, so the pipeline always produces the canonical schema.
