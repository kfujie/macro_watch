# macro_watch

Production-grade toolkit for **weekly cross-asset macro market analysis**. It ingests, aligns,
computes, and visualizes macro-financial data to summarize the week's market regimes from a
macro trader's perspective.

## Package layout

```text
macro_watch/
├── __init__.py
├── data_loader.py      # MoF (JGB), FRED, Yahoo ingestion + Parquet caching
├── analytics.py        # curves, real rates, rolling correlations, z-scores
├── visualizer.py       # production-quality plots for the weekly brief
└── weekly_report.ipynb # orchestrates the pipeline and renders the dashboard
```

## Data sources

| Block       | Series                                                      | Source |
|-------------|-------------------------------------------------------------|--------|
| JP rates    | JGB 2Y / 5Y / 10Y / 20Y / 30Y / 40Y                         | MoF Japan (Shift-JIS CSV, Japanese-era dates) |
| US rates    | UST 2Y / 3Y / 5Y / 7Y / 10Y / 20Y / 30Y, T10YIE (10Y breakeven) | FRED (keyless `fredgraph.csv`) |
| Commodities | WTI (`DCOILWTICO`), Gold                                    | FRED / Yahoo `GC=F` |
| Equities    | `^GSPC`, `^IXIC`, `^N225`, `^TOPX`                          | Yahoo Finance (adjusted close) |

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
- **Weekly transition** (`weekly_transition`) — week-ending (W-FRI) levels across the last N
  weeks for tenors / slopes / flies, with the latest `WoW(bp)`.

## Visualizations

1. **Weekly cross-asset z-score heatmap** — magnitude of the week's moves across all blocks.
2. **Macro decoupling tracker** — dual-axis real-rates/gold and WTI/breakevens.
3. **Rolling correlations** — 30d/60d time series for the key macro pairs.
4. **Curve snapshot & weekly shift** — full UST / JGB curve (current vs 1W / 1M) + per-tenor WoW bars.
5. **Curve momentum/richness heatmap** — slope & fly `Z_1W` and `Z_level` for both markets.
6. **Slopes & butterflies** — *actual spread* (bp) time series with mean and ±1σ/±2σ bands.
7. **Curve PCA** — loadings, factor history, and rich/cheap residual bars.
8. **Weekly curve transition** — full curve overlaid at the last N weekly closes (oldest→newest)
   plus the week-on-week change by tenor.
9. **Butterfly weekly transition** — each fly's level (bp) across the last N weekly closes with
   the latest week-on-week change.
10. **Butterfly daily — last week** — the daily path of each fly over the last 5 sessions
    (`daily_transition` / `plot_spread_daily`), last week shaded, with the WoW move per fly.

## Setup (uv)

```bash
uv sync                          # install dependencies into .venv
uv run jupyter lab macro_watch/weekly_report.ipynb
```

Programmatic use:

```python
from macro_watch.data_loader import MacroDataLoader
from macro_watch import analytics, visualizer

panel = MacroDataLoader().load(refresh=True)   # fetch + cache (Parquet)
summary = analytics.weekly_summary(panel)      # levels / WoW / z-scores
visualizer.apply_style()
visualizer.plot_weekly_heatmap(panel)
```

The loader degrades gracefully: any single source that fails is skipped (with a warning) and its
columns are emitted as `NaN`, so the pipeline always produces the canonical schema.
