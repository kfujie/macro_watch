"""Export the weekly macro panel + analytics to a single JSON for the web view.

The Python layer stays the single source of truth for ingestion and analytics
(the MoF/FRED/Yahoo quirks and the rates math live in :mod:`macro_watch`); this
module just serializes the snapshot artifacts the notebook used to render into a
flat ``data.json`` that the experimental Vite/TS front-end (``web/``) consumes.

Run:  ``uv run python -m macro_watch.web_export``  (writes ``web/public/data.json``)
       ``uv run python -m macro_watch.web_export --refresh``  (re-fetch sources)
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from macro_watch import analytics, sectors
from macro_watch.analytics import CURVES
from macro_watch.data_loader import MacroDataLoader

# ~2y of daily history is plenty for the front-end charts while keeping the
# payload small.
SERIES_TAIL: int = 504


# --------------------------------------------------------------------------- #
# JSON-safe coercion
# --------------------------------------------------------------------------- #
def _clean(obj: Any) -> Any:
    """Recursively coerce numpy/pandas/NaN into JSON-serializable primitives."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if (obj is None or math.isnan(float(obj))) else float(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return obj.date().isoformat()
    if obj is pd.NaT or obj is None:
        return None
    return obj


def _records(frame: pd.DataFrame, *, index_name: str) -> list[dict[str, Any]]:
    """DataFrame -> list of row dicts with the index exposed as ``index_name``."""
    out = frame.reset_index()
    out = out.rename(columns={out.columns[0]: index_name})
    return _clean(out.to_dict(orient="records"))


def _series(series: pd.Series) -> list[dict[str, Any]]:
    """Datetime-indexed Series -> ``[{date, value}, ...]`` (tail-trimmed)."""
    s = series.dropna().tail(SERIES_TAIL)
    return [{"date": d.date().isoformat(), "value": _clean(v)} for d, v in s.items()]


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #
def _curve_snapshot(panel: pd.DataFrame, market: str) -> dict[str, Any]:
    """Current/1W/1M curve levels + the WoW shift, for the curve chart."""
    curve = CURVES[market]
    tenors = list(curve)
    cols = list(curve.values())
    lvl = panel[cols].dropna(how="all")
    as_of = lvl.index.max()
    offsets = {
        "Current": as_of,
        "1W ago": lvl.index[lvl.index <= as_of - pd.Timedelta(days=7)].max(),
        "1M ago": lvl.index[lvl.index <= as_of - pd.Timedelta(days=30)].max(),
    }
    snapshots = [
        {
            "label": label,
            "date": ts.date().isoformat(),
            "yields": _clean(lvl.loc[ts, cols].tolist()),
        }
        for label, ts in offsets.items()
        if not pd.isna(ts)
    ]
    cur, prev = offsets["Current"], offsets["1W ago"]
    wow = (
        ((lvl.loc[cur, cols] - lvl.loc[prev, cols]) * 100.0).tolist()
        if not pd.isna(prev)
        else [None] * len(cols)
    )
    return {"tenors": tenors, "snapshots": snapshots, "wow_shift_bp": _clean(wow)}


def _pca(panel: pd.DataFrame, market: str) -> dict[str, Any]:
    pca = analytics.curve_pca(panel, market)
    loadings = pca.loadings.copy()
    loadings.index = [c.replace(market, "") for c in loadings.index]
    rich = pca.rich_cheap.copy()
    rich.index = [c.replace(market, "") for c in rich.index]
    return {
        "as_of": pca.as_of.date().isoformat(),
        "loadings": _records(loadings, index_name="tenor"),
        "explained": _clean(pca.explained.to_dict()),
        "rich_cheap": _clean([{"tenor": t, "bp": v} for t, v in rich.items()]),
    }


def _butterflies(panel: pd.DataFrame, market: str) -> dict[str, Any]:
    """Each fly's tenor-weighted spread (bp) over the lookback, for the band panels.

    Mean / ±σ bands and the latest z are computed client-side over exactly these
    points, matching ``visualizer.plot_butterflies`` (belly cheap = positive).
    """
    metrics = analytics.curve_metrics(panel, market).tail(SERIES_TAIL)
    flies = [c for c in metrics.columns if str(c).count("s") == 3]
    series = [
        {
            "name": c.replace(f"{market}_", ""),
            "points": _series(metrics[c]),
        }
        for c in flies
    ]
    return {"lookback": SERIES_TAIL, "series": series}


def _market(panel: pd.DataFrame, market: str) -> dict[str, Any]:
    return {
        "curve": _curve_snapshot(panel, market),
        "tenor_table": _records(
            analytics.tenor_snapshot(panel, market), index_name="tenor"
        ),
        "rates_table": _records(
            analytics.rates_snapshot(panel, market), index_name="metric"
        ),
        "butterflies": _butterflies(panel, market),
        "pca": _pca(panel, market),
    }


def _fx(panel: pd.DataFrame) -> dict[str, Any]:
    fv = analytics.fx_rate_fairvalue(panel, "USDJPY", tenor=10, lookback=SERIES_TAIL)
    diff = analytics.rate_differential(panel, 10)
    return {
        "table": _records(analytics.fx_snapshot(panel), index_name="pair"),
        "usdjpy": _series(panel["USDJPY"]),
        "differential": _series(diff),
        "fairvalue": {
            "driver": fv.driver,
            "beta": _clean(fv.beta),
            "r2": _clean(fv.r2),
            "resid_z": _clean(fv.resid_z),
            "fitted": _series(fv.fitted),
            "residual": _series(fv.residual),
        },
    }


def _oil_vs_bei(panel: pd.DataFrame) -> dict[str, Any]:
    """WTI crude vs 10Y breakeven inflation (structurally positively correlated)."""
    corr = analytics.rolling_correlations(panel)
    corr_series = corr["WTI_vs_BEI_60d"].dropna() if "WTI_vs_BEI_60d" in corr else None
    wti, bei = panel["WTI"].dropna(), panel["US10Y_BEI"].dropna()
    return {
        "wti": _series(panel["WTI"]),
        "bei": _series(panel["US10Y_BEI"]),
        "wti_level": _clean(wti.iloc[-1]) if len(wti) else None,
        "bei_level": _clean(bei.iloc[-1]) if len(bei) else None,
        "corr_60d": _clean(corr_series.iloc[-1]) if corr_series is not None and len(corr_series) else None,
    }


def _correlations(panel: pd.DataFrame) -> dict[str, Any]:
    """Strongest co-moving pairs over the last month + the leader's z-score paths."""
    window = analytics.MONTH
    pairs = analytics.top_correlated_pairs(panel, window=window, top_n=8)
    ranked = [{"a": p.a, "b": p.b, "corr": _clean(p.corr), "n": p.n_obs} for p in pairs]
    highlight: Any = None
    if pairs:
        top = pairs[0]
        lv = analytics.augment(panel)[[top.a, top.b]].dropna().tail(window)
        z = (lv - lv.mean()) / lv.std(ddof=0).replace(0.0, np.nan)
        highlight = {
            "a": top.a,
            "b": top.b,
            "corr": _clean(top.corr),
            "n": top.n_obs,
            "series": [
                {"date": d.date().isoformat(), "a": _clean(z.at[d, top.a]), "b": _clean(z.at[d, top.b])}
                for d in lv.index
            ],
        }
    return {"window_days": window, "ranked": ranked, "highlight": highlight}


def build_payload(panel: pd.DataFrame, *, refresh: bool = False) -> dict[str, Any]:
    """Assemble the full front-end payload from the canonical panel."""
    as_of = panel.dropna(how="all").index.max()
    zmatrix = analytics.weekly_zscore_matrix(panel)
    return {
        "as_of": as_of.date().isoformat(),
        "markets": {m: _market(panel, m) for m in CURVES},
        "fx": _fx(panel),
        "equities": _clean(sectors.build_equities(panel, refresh=refresh)),
        "cross_asset": {
            "zscores": _clean(
                [{"asset": a, "z": v} for a, v in zmatrix.dropna().items()]
            ),
            "oil_vs_bei": _oil_vs_bei(panel),
            "correlations": _correlations(panel),
        },
    }


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def export(out_path: Path, *, refresh: bool = False) -> Path:
    panel = MacroDataLoader().load(refresh=refresh)
    payload = build_payload(panel, refresh=refresh)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, allow_nan=False))
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export macro panel to data.json")
    parser.add_argument(
        "--refresh", action="store_true", help="Re-fetch all sources before exporting."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "web" / "public" / "data.json",
        help="Output path for data.json.",
    )
    args = parser.parse_args()
    path = export(args.out, refresh=args.refresh)
    size_kb = path.stat().st_size / 1024
    print(f"Wrote {path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
