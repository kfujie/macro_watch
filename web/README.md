# macro_watch — web view

The dashboard. Python stays the source of truth for ingestion + analytics; it
exports one `public/data.json`, and this Vite + TypeScript +
[Observable Plot](https://observablehq.com/plot/) app renders the rates / FX /
cross-asset brief from it.

## Pipeline

```
macro_watch (Python)            web/ (TypeScript)
  data_loader + analytics   →   public/data.json   →   Plot charts + tables
  └─ web_export.py (dumps JSON)
```

## Use

1. Generate the data (from the repo root):
   ```
   uv run python -m macro_watch.web_export            # uses the Parquet cache
   uv run python -m macro_watch.web_export --refresh  # re-fetch all sources
   ```
   Writes `web/public/data.json`.

2. Run the dev server (from `web/`):
   ```
   npm install      # first time
   npm run dev      # http://localhost:5173
   ```
   `npm run build` → static bundle in `dist/`.

## Layout

- `src/types.ts` — the `data.json` schema (kept in sync with `web_export.py`).
- `src/charts.ts` — Observable Plot charts (curve snapshot, PCA, FX fair value,
  sector contribution, z-scores).
- `src/ui.ts` — DOM + table helpers (sign-colored, per-column formatting).
- `src/theme.ts` — **time-of-day theme**: surfaces wash between a dark palette
  (midnight) and a light one (local noon, white background); text snaps to the
  contrasting extreme so it stays readable through dawn/dusk. Re-applied every
  5 min so a long-open tab tracks the day.
- `src/main.ts` — fetches `data.json` and assembles the page.

## Sections

- **Rates**: US & JGB curve snapshot, slopes/flies tables, **slope** and **butterfly** spread
  panels (bp with mean and ±1σ/±2σ bands; steeper = up, belly cheap = up), and curve PCA.
- **FX**: USD/JPY vs the US–JP 10Y differential.
- **Equities**: S&P 500 & Nikkei 225 — each index move decomposed into sector
  contributions (`weight × sector return`), with a WoW/1M toggle. Sector proxies
  are the SPDR Select Sector ETFs (US) and NEXT FUNDS TOPIX-17 ETFs (Japan); see
  `macro_watch/sectors.py`. Index weights are a documented static approximation,
  so a residual vs the actual index return is shown for honesty.
- **Cross-asset**: 1-week momentum z-score row.

Sector ETF prices are cached separately (`data_cache/sector_panel.parquet`) and
never touch the canonical panel's `CANONICAL_COLUMNS`.

## Extending

A new analytic = a field in `web_export.py` + a type in `src/types.ts` + a chart
or table in `src/`. The front-end does no computation.

## Note on the build

`npm run build` runs `tsc --noEmit` (type-check only) then `vite build`. Don't
remove `noEmit` from `tsconfig.json`: a bare `tsc` would emit `src/*.js` next to
the sources, and Vite resolves `.js` before `.ts`, so stale emitted files would
silently shadow the real modules.
