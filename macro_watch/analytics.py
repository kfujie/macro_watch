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
# Rates curve definitions (tenor in years -> canonical column)
# --------------------------------------------------------------------------- #
US_CURVE: Final[dict[int, str]] = {
    2: "US2Y",
    3: "US3Y",
    5: "US5Y",
    7: "US7Y",
    10: "US10Y",
    20: "US20Y",
    30: "US30Y",
}
JP_CURVE: Final[dict[int, str]] = {
    2: "JP2Y",
    5: "JP5Y",
    10: "JP10Y",
    20: "JP20Y",
    30: "JP30Y",
    40: "JP40Y",
}
CURVES: Final[Mapping[str, dict[int, str]]] = {"US": US_CURVE, "JP": JP_CURVE}

# Slope (short, long) and butterfly (short, belly, long) structures, in years.
US_SLOPES: Final[tuple[tuple[int, int], ...]] = (
    (2, 5), (2, 10), (5, 10), (5, 30), (10, 30), (2, 30),
)
US_FLIES: Final[tuple[tuple[int, int, int], ...]] = (
    (2, 5, 10), (5, 7, 10), (5, 10, 30), (10, 20, 30),
)
JP_SLOPES: Final[tuple[tuple[int, int], ...]] = (
    (2, 10), (5, 10), (10, 20), (10, 30), (20, 30), (2, 30), (5, 30),
)
JP_FLIES: Final[tuple[tuple[int, int, int], ...]] = (
    (2, 5, 10), (5, 10, 20), (10, 20, 30), (20, 30, 40),
)
CURVE_STRUCTURES: Final[
    Mapping[str, tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int, int], ...]]]
] = {"US": (US_SLOPES, US_FLIES), "JP": (JP_SLOPES, JP_FLIES)}

BP: Final[float] = 100.0  # percentage points -> basis points


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
# Rates: curves, slopes, butterflies, rich/cheap (US Treasury & JGB)
# --------------------------------------------------------------------------- #
def _slope_name(market: str, a: int, b: int) -> str:
    return f"{market}_{a}s{b}s"


def _fly_name(market: str, s: int, b: int, lo: int) -> str:
    return f"{market}_{s}s{b}s{lo}s"


def curve_levels(panel: pd.DataFrame, market: str) -> pd.DataFrame:
    """Outright yield levels for a market's curve, columns ordered by tenor."""
    cols = list(CURVES[market].values())
    return panel[cols]


def curve_metrics(panel: pd.DataFrame, market: str) -> pd.DataFrame:
    """All curve slopes and butterflies for ``market`` as time series (bps).

    Slope ``AsBs`` = (yield_B - yield_A) * 100.
    Butterfly ``AsBsCs`` = (2*belly - short - long) * 100; positive = belly cheap.
    """
    curve = CURVES[market]
    slopes, flies = CURVE_STRUCTURES[market]
    out = pd.DataFrame(index=panel.index)
    for a, b in slopes:
        out[_slope_name(market, a, b)] = (panel[curve[b]] - panel[curve[a]]) * BP
    for s, b, lo in flies:
        out[_fly_name(market, s, b, lo)] = (
            2.0 * panel[curve[b]] - panel[curve[s]] - panel[curve[lo]]
        ) * BP
    return out


def _change_zscore(metric: pd.DataFrame, horizon: int, window: int) -> pd.DataFrame:
    """Z-score of an ``horizon``-session change vs rolling daily-change vol."""
    vol = metric.diff().rolling(window, min_periods=max(5, window // 3)).std(ddof=0)
    return metric.diff(horizon) / (vol * np.sqrt(horizon)).replace(0.0, np.nan)


def rates_snapshot(
    panel: pd.DataFrame,
    market: str,
    *,
    window: int = VOL_WINDOW,
    pct_lookback: int = 252,
) -> pd.DataFrame:
    """Current curve slopes & flies with WoW/1M moves, momentum & level z-scores.

    * ``Z_1W``   : momentum z-score of this week's move (vol-normalized).
    * ``Z_level``: richness of the current level vs its trailing distribution.
    * ``Pctile`` : percentile of the current level over ``pct_lookback`` sessions.
    """
    m = curve_metrics(panel, market).dropna(how="all")
    as_of = m.index.max()

    z1 = _change_zscore(m, WEEK, window)
    lvl_mean = m.rolling(pct_lookback, min_periods=20).mean()
    lvl_sd = m.rolling(pct_lookback, min_periods=20).std(ddof=0)
    z_level = (m - lvl_mean) / lvl_sd.replace(0.0, np.nan)
    pctile = m.tail(pct_lookback).rank(pct=True)

    table = pd.DataFrame(index=m.columns)
    table["Level(bp)"] = m.loc[as_of]
    table["WoW(bp)"] = m.diff(WEEK).loc[as_of]
    table["1M(bp)"] = m.diff(MONTH).loc[as_of]
    table["Z_1W"] = z1.loc[as_of]
    table["Z_level"] = z_level.loc[as_of]
    table["Pctile"] = pctile.loc[as_of] * 100.0
    table["Kind"] = ["Fly" if c.count("s") == 3 else "Slope" for c in table.index]
    return table.round(3)


def tenor_snapshot(
    panel: pd.DataFrame, market: str, *, window: int = VOL_WINDOW
) -> pd.DataFrame:
    """Outright tenor levels with WoW/1M changes (bps) and momentum z-scores."""
    lv = curve_levels(panel, market).dropna(how="all")
    as_of = lv.index.max()
    chg = lv.diff() * BP
    vol = chg.rolling(window, min_periods=max(5, window // 3)).std(ddof=0)
    z1 = (lv.diff(WEEK) * BP) / (vol * np.sqrt(WEEK)).replace(0.0, np.nan)

    table = pd.DataFrame(index=lv.columns)
    table["Yield(%)"] = lv.loc[as_of]
    table["WoW(bp)"] = (lv.diff(WEEK) * BP).loc[as_of]
    table["1M(bp)"] = (lv.diff(MONTH) * BP).loc[as_of]
    table["Z_1W"] = z1.loc[as_of]
    return table.round(3)


@dataclass
class PCAResult:
    """Level/slope/curvature decomposition of a yield curve."""

    as_of: pd.Timestamp
    market: str
    scores: pd.DataFrame          # PC time series (PC1..PCn)
    loadings: pd.DataFrame        # tenor x PC
    explained: pd.Series          # explained-variance ratio per PC
    rich_cheap: pd.Series         # latest 3-factor residual per tenor (bps, + = cheap)


def _orient_loadings(load: np.ndarray) -> np.ndarray:
    """Sign-normalize PCs so PC1=level, PC2=slope, PC3=curvature are comparable."""
    out = load.copy()
    n_tenors = out.shape[1]
    # PC1: positive level shift.
    if out[0].sum() < 0:
        out[0] *= -1
    # PC2: upward-sloping (long end > short end).
    if out.shape[0] > 1 and out[1, -1] < out[1, 0]:
        out[1] *= -1
    # PC3: positive curvature (belly above the wing average).
    if out.shape[0] > 2:
        mid = n_tenors // 2
        if out[2, mid] < 0.5 * (out[2, 0] + out[2, -1]):
            out[2] *= -1
    return out


def curve_pca(
    panel: pd.DataFrame, market: str, *, lookback: int = 252, n_components: int = 3
) -> PCAResult:
    """PCA of the yield-curve levels: factors, loadings, and rich/cheap residuals.

    Residual = actual - reconstruction from the first ``n_components`` factors;
    a positive residual means the tenor yields *more* than the model => cheap.
    """
    cols = list(CURVES[market].values())
    X = panel[cols].dropna()
    if lookback:
        X = X.tail(lookback)
    if len(X) < n_components + 1:
        raise ValueError(f"Insufficient history for {market} curve PCA ({len(X)} rows).")

    mean = X.mean()
    Xc = X.to_numpy() - mean.to_numpy()
    _, sv, vt = np.linalg.svd(Xc, full_matrices=False)
    load = _orient_loadings(vt[:n_components])          # (n, tenors)
    scores = Xc @ load.T                                # (T, n)
    evr = (sv**2 / np.sum(sv**2))[:n_components]
    fit = scores @ load + mean.to_numpy()
    resid_bps = (X.to_numpy()[-1] - fit[-1]) * BP

    names = [f"PC{i + 1}" for i in range(n_components)]
    return PCAResult(
        as_of=X.index.max(),
        market=market,
        scores=pd.DataFrame(scores, index=X.index, columns=names),
        loadings=pd.DataFrame(load.T, index=cols, columns=names),
        explained=pd.Series(evr, index=names, name="explained_var"),
        rich_cheap=pd.Series(resid_bps, index=cols, name="rich_cheap_bp"),
    )


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
