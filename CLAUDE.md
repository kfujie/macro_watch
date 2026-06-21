# CLAUDE.md — macro_watch

Weekly cross-asset macro toolkit. **US Treasury & JGB curve analysis is the primary focus**;
cross-asset (equity/commodity) is supporting context.

**The web dashboard (`web/`) is the display**; Python owns all compute. Python writes one
`web/public/data.json` (via `web_export.py`); the Vite + TypeScript + Observable Plot app renders
it — the front-end does **no** computation. Keep the two in sync: a new analytic = a field in
`web_export.py` + a type in `web/src/types.ts` + a chart/table in `web/src/`.

## Environment & commands
- **uv-managed**, Python 3.13. Run everything via `uv run` (e.g. `uv run python -c ...`).
- Smoke test: `uv run python -c "from macro_watch.data_loader import MacroDataLoader; MacroDataLoader().load()"`
- **Web (primary)**: `uv run python -m macro_watch.web_export [--refresh]` writes `web/public/data.json`;
  then `cd web && npm install && npm run dev` (http://localhost:5173). Static snapshot — re-run the
  export and reload when the data changes. `npm run build` runs `tsc --noEmit` (type-check only;
  **don't** drop `noEmit` — a bare `tsc` emits `src/*.js` that Vite resolves *before* the `.ts`
  sources and silently shadows them) then `vite build`.
- Package imports as `macro_watch.*` from the repo root.
- Private GitHub repo: `kfujie/macro_watch`. Commit only when asked.

## Layout
- `data_loader.py` — ingest (MoF/FRED/Yahoo), business-day align + ffill, Parquet cache.
- `analytics.py` — curves, real yield, momentum z-scores, rolling corr, **rates: curve_metrics /
  rates_snapshot / tenor_snapshot / curve_pca / weekly_transition / daily_transition**;
  **correlations: cross_asset_correlations / rates_structure_correlations** (see Conventions).
- `sectors.py` — S&P 500 / Nikkei 225 sector attribution (SPDR + TOPIX-17 ETF proxies) + index
  price history, cached to `data_cache/sector_panel.parquet` **separately** from the canonical
  panel (28 tickers stay out of `CANONICAL_COLUMNS`). Index weights are a documented static approx.
- `visualizer.py` — standalone matplotlib plot helpers (`plot_curve_snapshot`, `plot_curve_pca`,
  `plot_spreads`, `plot_butterflies`, `plot_spread_transition`, `plot_spread_daily`, …).
- `web_export.py` — serialize panel + analytics + sectors to `web/public/data.json` (NaN→null,
  dates→ISO; series tail-trimmed to `SERIES_TAIL=504`). One `_section` builder per web block.
- `web/` — **primary display**. `src/charts.ts` (Observable Plot), `src/theme.ts` (time-of-day
  theme), `src/ui.ts`, `src/main.ts`, `src/types.ts` (kept in lockstep with `web_export.py`).
  `public/data.json` is git-ignored (regenerated from sources).

## Web sections (`web/`, driven by `data.json`)
Rates per market (curve snapshot + WoW bars, outright/slope-fly tables, **butterfly** band panels,
PCA) → **rates slope/fly correlation** → **FX** (USD/JPY vs US−JP differential) → **equities**
(S&P 500 / Nikkei 225 price transition + **sector attribution**, WoW/1M toggle) → **cross-asset**
(oil vs breakeven, **strongest cross-asset correlation**, 1W z-score row). The page themes itself
by local time (`theme.ts`): white at noon, dark at midnight; charts read `--ink/--grid/--muted` CSS
vars at render time, so re-rendering recolors them.

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
- **Correlations** are Pearson on **daily increments** over the last month (`MONTH=20`), ranked by
  **|ρ|** (so strong negatives surface). Two deliberately-separated universes:
  - `cross_asset_correlations`: `MACRO_COLUMNS` (FX + commodities + equities + `US10Y_REAL`) plus
    curve **structures** (slopes/flies). **Outright tenors are excluded everywhere** (tenor-vs-tenor
    is mechanical), and a pair needs **≥1 macro leg** — so a structure (e.g. `US_5s10s30s`) only
    appears when it co-moves with a non-rate asset, never with another structure. `US10Y_REAL` is
    treated as macro (a cross-asset driver), not a rate — by design.
  - `rates_structure_correlations`: slopes/flies only (US+JP), **dropping pairs that share a tenor
    leg** (`_shares_leg`; 2s10s vs 5s10s share the 10Y → mechanical), surfacing cross-structure /
    cross-market relationships. A user explicitly did **not** want outright-tenor co-movement shown.

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
