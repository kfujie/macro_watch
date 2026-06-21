"""Macro analytics: curves, real rates, momentum z-scores, rolling correlations.

All functions are vectorized and operate on the canonical panel produced by
:mod:`macro_watch.data_loader`. Yields/breakevens are treated as *levels*
(percentage points); equities and commodities as *prices*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Final, Mapping

import numpy as np
import pandas as pd

from macro_watch.data_loader import (
    COMMODITY_COLUMNS,
    EQUITY_COLUMNS,
    FX_COLUMNS,
    RATE_COLUMNS,
)

# Columns measured as yields/levels (use absolute daily changes, not log returns).
YIELD_COLUMNS: Final[tuple[str, ...]] = RATE_COLUMNS
# Columns measured as prices (use log returns).
PRICE_COLUMNS: Final[tuple[str, ...]] = COMMODITY_COLUMNS + FX_COLUMNS + EQUITY_COLUMNS

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
    (2, 5),
    (2, 10),
    (5, 10),
    (5, 30),
    (10, 30),
    (2, 30),
)
US_FLIES: Final[tuple[tuple[int, int, int], ...]] = (
    (2, 5, 10),
    (5, 7, 10),
    (5, 10, 30),
    (10, 20, 30),
)
JP_SLOPES: Final[tuple[tuple[int, int], ...]] = (
    (2, 10),
    (5, 10),
    (10, 20),
    (10, 30),
    (20, 30),
    (2, 30),
    (5, 30),
)
JP_FLIES: Final[tuple[tuple[int, int, int], ...]] = (
    (2, 5, 10),
    (5, 10, 20),
    (10, 20, 30),
    (20, 30, 40),
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


def benchmark_yield_volatility(
    panel: pd.DataFrame,
    *,
    tenor: int = 10,
    window: int = MONTH,
    horizon: int = WEEK,
) -> pd.DataFrame:
    """Rolling realized volatility of each market's benchmark-tenor yield, in bp.

    For every curve in :data:`CURVES`, take the daily change of the ``tenor``-year
    yield, its rolling ``window``-session population std, then scale to a
    ``horizon``-session ("weekly") move (·√horizon) and to basis points (·100).
    Columns are market keys (``US``/``JP``); a market lacking the tenor, or whose
    benchmark is entirely NaN (e.g. JGB when MoF is unreachable), yields an all-NaN
    column that the exporter drops.
    """
    out = pd.DataFrame(index=panel.index)
    scale = float(np.sqrt(horizon)) * 100.0
    min_p = max(WEEK, window // 2)
    for market, curve in CURVES.items():
        col = curve.get(tenor)
        if col and col in panel:
            daily = panel[col].diff()
            out[market] = daily.rolling(window, min_periods=min_p).std(ddof=0) * scale
    return out


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


@dataclass
class CorrelationPair:
    """A pair of series and their Pearson correlation over a trailing window."""

    a: str
    b: str
    corr: float
    n_obs: int


# Non-rate macro series (the "cross-asset" universe): FX, commodities, equities,
# plus the real yield as a key macro driver. Outright tenors are deliberately
# excluded everywhere (tenor-vs-tenor co-movement is mechanical / uninformative).
MACRO_COLUMNS: Final[tuple[str, ...]] = (
    FX_COLUMNS + COMMODITY_COLUMNS + EQUITY_COLUMNS + ("US10Y_REAL",)
)

# A cross-asset pair is mechanical when its legs share a *building block*, just
# like curve structures sharing a tenor (_shares_leg). For FX that block is a
# currency (EURUSD/EURJPY share EUR; USDJPY/DXY share USD); for equities it is a
# region's constituents (SPX/NDX, N225/TOPIX). Such pairs are dropped from the
# cross-asset ranking, while genuinely cross-exposure pairs survive — SPX vs N225
# (different region) and WTI vs GOLD (different sector) are kept.
_FX_LEGS: Final[Mapping[str, frozenset[str]]] = {
    "USDJPY": frozenset({"USD", "JPY"}),
    "EURUSD": frozenset({"EUR", "USD"}),
    "EURJPY": frozenset({"EUR", "JPY"}),
    "DXY": frozenset({"USD"}),  # a USD basket; treated as its dollar leg
}
_EQUITY_PEERS: Final[tuple[frozenset[str], ...]] = (
    frozenset({"SPX", "NDX"}),  # US large-cap
    frozenset({"N225", "TOPIX"}),  # Japan large-cap
)


def _struct_columns(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Curve slope & butterfly time series per market (the rate *structures*)."""
    return {m: curve_metrics(panel, m) for m in CURVES}


def _struct_tenors(name: str) -> tuple[str, frozenset[int]]:
    """Parse a structure name (``US_5s10s30s``) into (market, {tenors})."""
    market, _, rest = name.partition("_")
    return market, frozenset(int(x) for x in re.findall(r"(\d+)s", rest))


def _shares_leg(a: str, b: str) -> bool:
    """True if two structures share a market and any tenor leg (mechanical overlap)."""
    ma, ta = _struct_tenors(a)
    mb, tb = _struct_tenors(b)
    return ma == mb and bool(ta & tb)


def _mechanical_macro_pair(a: str, b: str) -> bool:
    """True if a, b share a building block: a currency leg or an equity peer group."""
    la, lb = _FX_LEGS.get(a), _FX_LEGS.get(b)
    if la is not None and lb is not None and la & lb:
        return True
    return any({a, b} <= grp for grp in _EQUITY_PEERS)


def _rank_pairs(
    inc: pd.DataFrame,
    *,
    min_obs: int,
    keep: Callable[[str, str], bool],
) -> list[CorrelationPair]:
    """Pearson-correlate increment columns, keep pairs passing ``keep``, rank by |ρ|."""
    inc = inc.loc[:, inc.notna().sum() >= min_obs]
    corr = inc.corr(min_periods=min_obs)
    cols = list(corr.columns)
    pairs: list[CorrelationPair] = []
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            if not keep(a, b):
                continue
            r = corr.at[a, b]
            if pd.notna(r):
                n = int(inc[[a, b]].dropna().shape[0])
                pairs.append(CorrelationPair(a, b, float(r), n))
    pairs.sort(key=lambda p: abs(p.corr), reverse=True)
    return pairs


def cross_asset_levels(panel: pd.DataFrame) -> pd.DataFrame:
    """Level frame for cross-asset correlation: macro series + curve structures."""
    structs = _struct_columns(panel)
    return pd.concat([augment(panel)[list(MACRO_COLUMNS)], *structs.values()], axis=1)


def cross_asset_correlations(
    panel: pd.DataFrame, *, window: int = MONTH, min_obs: int = 15, top_n: int = 8
) -> list[CorrelationPair]:
    """Strongest macro pairs over the last ``window`` sessions, excluding pure rates.

    Universe = macro series (FX / commodities / equities / real yield) + curve
    structures (slopes & butterflies). Outright tenors are excluded, and a pair
    must include at least one macro leg — so a structure like ``US_5s10s30s``
    only appears when it co-moves with a non-rate asset (e.g. a yen cross), never
    paired with another structure. Pairs sharing a *building block* are also
    dropped as mechanical: FX crosses sharing a currency (EURUSD/EURJPY) and
    same-region equities (SPX/NDX). Genuinely cross-exposure pairs survive (SPX
    vs N225, WTI vs GOLD). Ranked by absolute correlation.
    """
    structs = {c for df in _struct_columns(panel).values() for c in df.columns}
    inc = _daily_increments(cross_asset_levels(panel)).tail(window)
    macro = set(MACRO_COLUMNS)

    def keep(a: str, b: str) -> bool:
        # require >=1 macro leg; the other may be macro or a structure. Pairs that
        # share a building block (currency leg or equity peer) are mechanical, so
        # drop them like outright tenors / shared-leg structures.
        return (
            (a in macro or b in macro)
            and not (a in structs and b in structs)
            and not _mechanical_macro_pair(a, b)
        )

    return _rank_pairs(inc, min_obs=min_obs, keep=keep)[:top_n]


def rates_structure_levels(panel: pd.DataFrame) -> pd.DataFrame:
    """Level frame of all curve slopes & butterflies (US + JP), bp."""
    return pd.concat(_struct_columns(panel).values(), axis=1)


def rates_structure_correlations(
    panel: pd.DataFrame, *, window: int = MONTH, min_obs: int = 15, top_n: int = 8
) -> list[CorrelationPair]:
    """Strongest slope/butterfly co-movements over the last ``window`` sessions.

    Universe = curve slopes & butterflies only (US + JP). Pairs sharing a market
    and a tenor leg are dropped (e.g. 2s10s vs 5s10s share the 10Y, so their high
    correlation is mechanical), surfacing genuine cross-structure / cross-market
    relationships. Ranked by absolute correlation.
    """
    inc = _daily_increments(rates_structure_levels(panel)).tail(window)
    return _rank_pairs(inc, min_obs=min_obs, keep=lambda a, b: not _shares_leg(a, b))[
        :top_n
    ]


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


def _fly_weights(short: int, belly: int, long: int) -> tuple[float, float]:
    """Tenor-distance wing weights so the belly sits on the wings' interpolation."""
    w_long = (belly - short) / (long - short)
    return 1.0 - w_long, w_long


def curve_metrics(
    panel: pd.DataFrame, market: str, *, fly_weighting: str = "tenor"
) -> pd.DataFrame:
    """All curve slopes and butterflies for ``market`` as time series (bps).

    Slope ``AsBs`` = (yield_B - yield_A) * 100.

    Butterfly ``AsBsCs`` measures belly curvature; positive = belly cheap (yield
    above the wings). Two conventions:

    * ``"tenor"`` (default): belly minus the *tenor-distance-weighted* wings, i.e.
      the belly's richness vs the straight line joining the wings in yield/tenor
      space. This is the correct sign for unevenly-spaced flies (e.g. 5s10s20s,
      where the 10Y belly is far from the 12.5Y midpoint of 5s/20s).
    * ``"equal"``: the simple ``2*belly - short - long`` (Bloomberg-style 2:1:1),
      which only reflects true curvature when the belly is the midpoint tenor.
    """
    curve = CURVES[market]
    slopes, flies = CURVE_STRUCTURES[market]
    out = pd.DataFrame(index=panel.index)
    for a, b in slopes:
        out[_slope_name(market, a, b)] = (panel[curve[b]] - panel[curve[a]]) * BP
    for s, b, lo in flies:
        if fly_weighting == "equal":
            val = 2.0 * panel[curve[b]] - panel[curve[s]] - panel[curve[lo]]
        else:  # "tenor": belly richness vs interpolated wings
            w_s, w_l = _fly_weights(s, b, lo)
            val = panel[curve[b]] - (w_s * panel[curve[s]] + w_l * panel[curve[lo]])
        out[_fly_name(market, s, b, lo)] = val * BP
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
    scores: pd.DataFrame  # PC time series (PC1..PCn)
    loadings: pd.DataFrame  # tenor x PC
    explained: pd.Series  # explained-variance ratio per PC
    rich_cheap: pd.Series  # latest 3-factor residual per tenor (bps, + = cheap)


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
        raise ValueError(
            f"Insufficient history for {market} curve PCA ({len(X)} rows)."
        )

    mean = X.mean()
    Xc = X.to_numpy() - mean.to_numpy()
    _, sv, vt = np.linalg.svd(Xc, full_matrices=False)
    load = _orient_loadings(vt[:n_components])  # (n, tenors)
    scores = Xc @ load.T  # (T, n)
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
# FX: dollar & yen (tie-in to the US-JP rate differential)
# --------------------------------------------------------------------------- #
FX_PRIMARY: Final[tuple[str, ...]] = ("USDJPY", "DXY")


def rate_differential(
    panel: pd.DataFrame, tenor: int = 10, *, base: str = "US", quote: str = "JP"
) -> pd.Series:
    """Nominal yield differential ``base - quote`` at ``tenor`` (bps).

    Default US-JP 10Y — the dominant macro driver of USD/JPY.
    """
    a, b = f"{base}{tenor}Y", f"{quote}{tenor}Y"
    return ((panel[a] - panel[b]) * BP).rename(f"{a}-{b}")


def fx_snapshot(panel: pd.DataFrame, *, window: int = VOL_WINDOW) -> pd.DataFrame:
    """FX levels with WoW/1M % moves and momentum z-scores.

    For USD-base pairs (USDJPY, DXY, EURJPY) a higher level = stronger USD/weaker
    quote; EURUSD is the exception (higher = weaker USD).
    """
    px = panel[list(FX_COLUMNS)].dropna(how="all")
    as_of = px.index.max()
    lr = _safe_log(px) if isinstance(px, pd.Series) else px.apply(_safe_log)
    daily = lr.diff()
    vol = daily.rolling(window, min_periods=max(5, window // 3)).std(ddof=0)

    table = pd.DataFrame(index=px.columns)
    table["Level"] = px.loc[as_of]
    table["WoW%"] = lr.diff(WEEK).loc[as_of] * 100.0
    table["1M%"] = lr.diff(MONTH).loc[as_of] * 100.0
    table["Z_1W"] = (lr.diff(WEEK) / (vol * np.sqrt(WEEK)).replace(0.0, np.nan)).loc[
        as_of
    ]
    table["Z_4W"] = (lr.diff(MONTH) / (vol * np.sqrt(MONTH)).replace(0.0, np.nan)).loc[
        as_of
    ]
    return table.round(3)


@dataclass
class FXFairValue:
    """OLS of an FX pair on a rate differential (yen rich/cheap vs rates)."""

    pair: str
    driver: str
    as_of: pd.Timestamp
    beta: float  # FX units per bp of differential
    alpha: float
    r2: float
    fitted: pd.Series  # model-implied FX level
    residual: pd.Series  # actual - fitted (FX units; + = pair rich vs rates)
    resid_z: float  # current residual in std units


def fx_rate_fairvalue(
    panel: pd.DataFrame,
    pair: str = "USDJPY",
    *,
    tenor: int = 10,
    lookback: int = 1260,
    base: str = "US",
    quote: str = "JP",
) -> FXFairValue:
    """Regress ``pair`` on the ``base-quote`` ``tenor`` differential over ``lookback``.

    The residual flags how far the pair trades from its rate-implied fair value
    (for USDJPY: positive residual = yen *cheaper* than the differential implies).
    The default ``lookback`` is ~5y to capture the structural (positive-beta)
    relationship; the sign can invert in short windows when other drivers (flows,
    real yields, intervention) dominate, so check ``r2``/``beta`` before trusting it.
    """
    diff = rate_differential(panel, tenor, base=base, quote=quote)
    df = pd.concat([panel[pair].rename(pair), diff], axis=1).dropna()
    if lookback:
        df = df.tail(lookback)
    if len(df) < 10:
        raise ValueError(f"Insufficient overlap for {pair} vs {diff.name} fair value.")

    x = df[diff.name].to_numpy()
    y = df[pair].to_numpy()
    beta, alpha = np.polyfit(x, y, 1)
    fitted = beta * x + alpha
    resid = y - fitted
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot else float("nan")
    sd = resid.std(ddof=0)

    return FXFairValue(
        pair=pair,
        driver=str(diff.name),
        as_of=df.index.max(),
        beta=float(beta),
        alpha=float(alpha),
        r2=float(r2),
        fitted=pd.Series(fitted, index=df.index, name="fitted"),
        residual=pd.Series(resid, index=df.index, name="residual"),
        resid_z=float(resid[-1] / sd) if sd else 0.0,
    )


# --------------------------------------------------------------------------- #
# Weekly z-score matrix (heatmap)
# --------------------------------------------------------------------------- #
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
