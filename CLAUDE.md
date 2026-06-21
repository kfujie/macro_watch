# CLAUDE.md — macro_watch

Weekly cross-asset macro toolkit. **US Treasury & JGB curve analysis is the primary focus**;
cross-asset (equity/commodity) is supporting context.

## Environment & commands
- **uv-managed**, Python 3.13. Run everything via `uv run` (e.g. `uv run python -c ...`).
- Smoke test: `uv run python -c "from macro_watch.data_loader import MacroDataLoader; MacroDataLoader().load()"`
- Execute the notebook headless:
  `cd macro_watch && uv run jupyter nbconvert --to notebook --execute --inplace weekly_report.ipynb --ExecutePreprocessor.timeout=300`
- Package imports as `macro_watch.*` from the repo root (the notebook adds the parent to `sys.path`).
- Private GitHub repo: `kfujie/macro_watch`. Commit only when asked.

## Layout
- `data_loader.py` — ingest (MoF/FRED/Yahoo), business-day align + ffill, Parquet cache.
- `analytics.py` — curves, real yield, momentum z-scores, rolling corr, **rates: curve_metrics /
  rates_snapshot / tenor_snapshot / curve_pca / weekly_transition / daily_transition**.
- `visualizer.py` — all plots (`plot_curve_snapshot`, `plot_curve_pca`, `plot_spreads`,
  `plot_butterflies`, `plot_spread_transition`, `plot_spread_daily`, `plot_curve_transition`, …).
- `weekly_report.ipynb` — §1 ingest, **§2 US Treasury & JGB (main)**, §3 cross-asset backdrop,
  §4 markdown brief (leads with rates). `REFRESH=False` uses the cache.

## Data-source quirks (these took digging — don't relitigate)
- **MoF JGB**: Shift-JIS CSV, **Japanese-era dates** (`R8.6.1` = Reiwa→2026; offsets in `_ERA_OFFSET`).
  Spec URL `jgbcm.csv` is **current month only**; full history is `.../interest_rate/data/jgbcm_all.csv`.
  `load_jgb` combines both. The MoF endpoint is **flaky/intermittently times out** → `_get_with_retry`
  (default 4 tries). If all JGB fetches fail, JP columns come back **all-NaN by design** (graceful
  degradation), not an error.
- **FRED**: use the keyless `fredgraph.csv` endpoint via `requests`. Do **NOT** use
  `pandas-datareader` — it imports `distutils`, which is gone in Python 3.13. FRED **silently omits
  de-listed series** from multi-id CSVs (warn, don't crash).
- **Gold**: spec's `GOLDAMGBD228NLBM` is **de-listed (HTTP 404)** → gold comes from **Yahoo `GC=F`**.
- **TOPIX (`^TOPX`)**: no free Yahoo history → the `TOPIX` column is **all-NaN**, handled gracefully
  (dropped from the heatmap).
- **FX (Yahoo)**: USD/JPY = `JPY=X`, dollar index = `DX-Y.NYB` (NOT `DX=F`, which 404s),
  `EURUSD=X`, `EURJPY=X`. Yen & dollar are the primary FX focus. The USD/JPY↔(US−JP rate
  differential) **regression beta is regime-dependent**: positive over multi-year windows, but it
  inverts in short windows — `fx_rate_fairvalue` defaults to a ~5y (`lookback=1260`) window for the
  structural relationship. Don't "fix" a negative short-window beta; it's real.
- **JGB lags US by ~1 session**: MoF prints a day behind FRED/Yahoo, so the latest JGB values are
  often `ffill`ed to the as-of date.

## Conventions (deliberate — keep)
- **Butterflies are tenor-weighted by default** (belly minus the wings' yield/tenor interpolation),
  so the sign is correct for unevenly-spaced flies (e.g. 5s10s20s). **Positive = belly cheap.**
  `curve_metrics(..., fly_weighting="equal")` gives the simple 2:1:1 fly. (A user flagged that the
  old 2:1:1 returned the wrong sign for 5s10s20s — that's why this exists.)
- **Slopes** `AsBs` = `(yield_B − yield_A)·100` bp; positive = steeper.
- Yields/spreads use **absolute diffs**; prices (equities, gold, WTI) use **log returns**.
  `RATE_COLUMNS` ⊂ yields; `PRICE_COLUMNS` = commodities + equities.
- z-scores: horizon move normalized by `σ_daily·√horizon` over a rolling 90d window.
- **Curve plots use evenly-spaced category x-positions** (`np.arange(len(tenors))`) with tenor
  tick labels — NOT maturity-proportional. (Fixed a bug where a numeric line + categorical bar
  under `sharex=True` misaligned the ticks.)
- PCA loadings are **sign-normalized** so PC1≈level, PC2≈slope, PC3≈curvature; rich/cheap residual
  is actual − 3-factor fit (+ = cheap).

## Cache / schema
- `CANONICAL_COLUMNS` in `data_loader.py` is the fixed schema; the Parquet cache
  (`data_cache/macro_panel.parquet`, git-ignored) is **validated against it and refetched on
  mismatch**. Adding/removing tenors changes the schema and invalidates old caches (expected).
- If a `MacroDataLoader().update()` lands while MoF is down, the saved cache will have NaN JP
  columns. To reseed cleanly, fetch sources independently and retry `load_jgb()` until
  `JP10Y.notna().any()`, then `align_frames([...]) ` + `.save()`.

## Style
- High type-hint coverage; vectorized pandas/numpy; minimal comments. A linter reformats on save —
  don't fight it.
