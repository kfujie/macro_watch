"""Macro analytics: curves, real rates, momentum z-scores, rolling correlations.

All functions are vectorized and operate on the canonical panel produced by
:mod:`macro_watch.data_loader`. Yields/breakevens are treated as *levels*
(percentage points); equities and commodities as *prices*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping

import numpy as np
import pandas as pd

from macro_watch.data_loader import (
    COMMODITY_COLUMNS,
    EQUITY_COLUMNS,
    RATE_COLUMNS,
)

# Columns measured as yields/levels (use absolute daily changes, not log returns).
YIELD_COLUMNS: Final[tuple[str, ...]] = RATE_COLUMNS
# Columns measured as prices (use log returns).
PRICE_COLUMNS: Final[tuple[str, ...]] = COMMODITY_COLUMNS + EQUITY_COLUMNS

WEEK: Final[int] = 5  # trading sessions per week
MONTH: Final[int] = 20  # trading sessions per month
VOL_WINDOW: Final[int] = 90  # rolling volatility lookback (sessions)
ANNUALIZER: Final[float] = float(np.sqrt(252))

# Key macro pairs for rolling-correlation diagnostics.
CORRELATION_PAIRS: Final[Mapping[str, tuple[str, str]]] = {
    "RealYield_vs_Gold": ("US10Y_REAL", "GOLD"),
    "WTI_vs_BEI": ("WTI", "US10Y_BEI"),
    "SPX_vs_US10Y": ("SPX", "US10Y"),
}


# --------------------------------------------------------------------------- #
# Curves & real rates
# --------------------------------------------------------------------------- #
def yield_curve_slopes(panel: pd.DataFrame) -> pd.DataFrame:
    """10Y-2Y slopes (in basis points) for US and JP."""
    out = pd.DataFrame(index=panel.index)
    out["US_10s2s"] = (panel["US10Y"] - panel["US2Y"]) * 100.0
    out["JP_10s2s"] = (panel["JP10Y"] - panel["JP2Y"]) * 100.0
    return out


def us_real_yield(panel: pd.DataFrame) -> pd.Series:
    """US 10Y real yield = nominal 10Y - 10Y breakeven inflation."""
    return (panel["US10Y"] - panel["US10Y_BEI"]).rename("US10Y_REAL")


def augment(panel: pd.DataFrame) -> pd.DataFrame:
    """Return the panel with derived series (real yield, slopes) appended."""
    enriched = panel.copy()
    enriched["US10Y_REAL"] = us_real_yield(panel)
    slopes = yield_curve_slopes(panel)
    enriched["US_10s2s"] = slopes["US_10s2s"]
    enriched["JP_10s2s"] = slopes["JP_10s2s"]
    return enriched


# --------------------------------------------------------------------------- #
# Momentum / z-scores
# --------------------------------------------------------------------------- #
def _safe_log(series: pd.Series) -> pd.Series:
    """log of strictly-positive values; non-positive/NaN map to NaN, no warning."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.log(series.where(series > 0))


def _daily_increments(panel: pd.DataFrame) -> pd.DataFrame:
    """Daily log returns for prices, absolute diffs for yields."""
    inc = pd.DataFrame(index=panel.index)
    for col in panel.columns:
        if col in PRICE_COLUMNS:
            inc[col] = _safe_log(panel[col]).diff()
        else:  # yields / spreads / levels
            inc[col] = panel[col].diff()
    return inc


def rolling_volatility(
    panel: pd.DataFrame, window: int = VOL_WINDOW, *, annualize: bool = True
) -> pd.DataFrame:
    """Rolling std of daily increments (annualized) per asset."""
    inc = _daily_increments(panel)
    vol = inc.rolling(window, min_periods=max(5, window // 3)).std(ddof=0)
    return vol * ANNUALIZER if annualize else vol


def horizon_change(panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Change over ``horizon`` sessions: log return for prices, diff for yields."""
    out = pd.DataFrame(index=panel.index)
    for col in panel.columns:
        if col in PRICE_COLUMNS:
            out[col] = _safe_log(panel[col]).diff(horizon)
        else:
            out[col] = panel[col].diff(horizon)
    return out


def momentum_zscores(panel: pd.DataFrame, *, window: int = VOL_WINDOW) -> pd.DataFrame:
    """Z-scores of 1-week and 4-week moves vs rolling daily volatility.

    A horizon-``h`` move is normalized by the volatility expected over ``h``
    sessions: ``sigma_daily * sqrt(h)`` (de-annualized rolling vol).
    """
    daily_vol = rolling_volatility(panel, window=window, annualize=False)
    out = pd.DataFrame(index=panel.index)
    for horizon, label in ((WEEK, "1W"), (MONTH, "4W")):
        change = horizon_change(panel, horizon)
        scale = daily_vol * np.sqrt(horizon)
        out[[f"{c}_z{label}" for c in change.columns]] = change.div(
            scale.replace(0.0, np.nan)
        ).to_numpy()
    return out


# --------------------------------------------------------------------------- #
# Rolling correlations
# --------------------------------------------------------------------------- #
def rolling_correlations(
    panel: pd.DataFrame,
    pairs: Mapping[str, tuple[str, str]] = CORRELATION_PAIRS,
    windows: tuple[int, ...] = (30, 60),
) -> pd.DataFrame:
    """Rolling Pearson correlations of daily increments for macro pairs."""
    enriched = augment(panel)
    inc = _daily_increments(enriched)
    out = pd.DataFrame(index=panel.index)
    for name, (a, b) in pairs.items():
        if a not in inc or b not in inc:
            continue
        for win in windows:
            out[f"{name}_{win}d"] = (
                inc[a].rolling(win, min_periods=max(5, win // 2)).corr(inc[b])
            )
    return out


# --------------------------------------------------------------------------- #
# Weekly summary
# --------------------------------------------------------------------------- #
@dataclass
class WeeklySummary:
    """Container for the current-week snapshot artifacts."""

    as_of: pd.Timestamp
    table: pd.DataFrame  # level / WoW / z-score per asset
    ohlc: pd.DataFrame  # O/H/L/C for the final week, per asset
    zscores: pd.DataFrame  # full z-score time series
    correlations: pd.DataFrame  # rolling correlations time series


def _week_window(index: pd.DatetimeIndex, as_of: pd.Timestamp) -> pd.DatetimeIndex:
    start = as_of - pd.Timedelta(days=6)
    return index[(index >= start) & (index <= as_of)]


def weekly_ohlc(panel: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Open/High/Low/Close over the final calendar week, per asset."""
    week = panel.loc[_week_window(panel.index, as_of)]
    return pd.DataFrame(
        {
            "Open": week.iloc[0],
            "High": week.max(),
            "Low": week.min(),
            "Close": week.iloc[-1],
        }
    )


def weekly_summary(panel: pd.DataFrame, *, window: int = VOL_WINDOW) -> WeeklySummary:
    """Build the current-week summary table, OHLC and supporting series."""
    enriched = augment(panel)
    as_of = enriched.dropna(how="all").index.max()

    zscores = momentum_zscores(enriched, window=window)
    correlations = rolling_correlations(panel)

    wow = horizon_change(enriched, WEEK)
    cols = [c for c in enriched.columns]
    table = pd.DataFrame(index=cols)
    table["Level"] = enriched.loc[as_of, cols]
    table["WoW"] = wow.loc[as_of, cols]
    table["Z_1W"] = [
        zscores.get(f"{c}_z1W", pd.Series(dtype=float)).get(as_of, np.nan) for c in cols
    ]
    table["Z_4W"] = [
        zscores.get(f"{c}_z4W", pd.Series(dtype=float)).get(as_of, np.nan) for c in cols
    ]
    table["Type"] = ["Price" if c in PRICE_COLUMNS else "Yield/Spread" for c in cols]

    ohlc = weekly_ohlc(enriched, as_of)
    return WeeklySummary(
        as_of=as_of, table=table, ohlc=ohlc, zscores=zscores, correlations=correlations
    )


def weekly_zscore_matrix(panel: pd.DataFrame, *, window: int = VOL_WINDOW) -> pd.Series:
    """Latest 1-week z-score per canonical asset (for the heatmap)."""
    enriched = augment(panel)
    z = momentum_zscores(enriched, window=window)
    as_of = enriched.dropna(how="all").index.max()
    assets = list(panel.columns) + ["US10Y_REAL", "US_10s2s", "JP_10s2s"]
    data = {
        a: z.get(f"{a}_z1W", pd.Series(dtype=float)).get(as_of, np.nan) for a in assets
    }
    return pd.Series(data, name=str(as_of.date()))
