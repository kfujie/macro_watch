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
| JP rates    | JGB 2Y / 5Y / 10Y                                           | MoF Japan (Shift-JIS CSV, Japanese-era dates) |
| US rates    | DGS2, DGS10, T10YIE (10Y breakeven)                         | FRED (keyless `fredgraph.csv`) |
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

- **Yield curves** — US / JP 10Y-2Y slopes (bps).
- **US real yield** — `US10Y_nominal − US10Y_BEI`.
- **Momentum z-scores** — 1-week (5d) and 4-week (20d) moves normalized by rolling 90-day daily
  volatility (`σ_daily · √horizon`); log returns for prices, absolute diffs for yields.
- **Rolling correlations** — 30d / 60d Pearson for Real Yield↔Gold, WTI↔BEI, S&P 500↔US10Y.

## Visualizations

1. **Weekly cross-asset z-score heatmap** — magnitude of the week's moves across all blocks.
2. **Yield-curve shifts** — US and JP curves: current vs 1 week / 1 month ago.
3. **Macro decoupling tracker** — dual-axis real-rates/gold and WTI/breakevens.
4. **Rolling correlations** — 30d/60d time series for the key macro pairs.

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
