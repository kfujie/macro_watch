"""Production-quality plots for the weekly macro brief."""

from __future__ import annotations

from typing import Final

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from macro_watch.analytics import (
    CURVES,
    PCAResult,
    augment,
    curve_metrics,
    curve_pca,
    rates_snapshot,
    weekly_zscore_matrix,
)

_STYLE: Final[str] = "seaborn-v0_8-whitegrid"


def apply_style() -> None:
    """Apply a clean, presentation-grade Matplotlib/Seaborn theme."""
    try:
        plt.style.use(_STYLE)
    except OSError:  # older matplotlib without the v0_8 alias
        plt.style.use("seaborn-whitegrid")
    sns.set_context("talk", font_scale=0.7)
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.titleweight": "bold",
            "axes.grid": True,
            "grid.alpha": 0.35,
        }
    )


# --------------------------------------------------------------------------- #
# 1. Cross-asset weekly z-score heatmap
# --------------------------------------------------------------------------- #
def plot_weekly_heatmap(panel: pd.DataFrame, *, ax: Axes | None = None) -> Figure:
    """Heatmap of the past week's z-scored move across all assets."""
    z = weekly_zscore_matrix(panel).dropna()
    if ax is None:
        _, ax = plt.subplots(figsize=(4.5, max(4.0, 0.42 * len(z))))
    sns.heatmap(
        z.to_frame("1W Z-score"),
        annot=True,
        fmt="+.2f",
        cmap="RdBu_r",
        center=0.0,
        vmin=-3.0,
        vmax=3.0,
        linewidths=0.5,
        cbar_kws={"label": "σ"},
        ax=ax,
    )
    ax.set_title(f"Weekly Cross-Asset Momentum (z-score)\nas of {z.name}")
    ax.set_ylabel("")
    return ax.figure


# --------------------------------------------------------------------------- #
# 2. Yield-curve shifts
# --------------------------------------------------------------------------- #
def _curve_points(panel: pd.DataFrame, prefix: str) -> list[str]:
    tenors = ["2Y", "5Y", "10Y"]
    return [f"{prefix}{t}" for t in tenors if f"{prefix}{t}" in panel.columns]


def _as_of_offsets(index: pd.DatetimeIndex) -> dict[str, pd.Timestamp]:
    as_of = index.max()
    return {
        "Current": as_of,
        "1 Week Ago": index[index <= as_of - pd.Timedelta(days=7)].max(),
        "1 Month Ago": index[index <= as_of - pd.Timedelta(days=30)].max(),
    }


def plot_curve_shifts(panel: pd.DataFrame) -> Figure:
    """US and JP curves: current vs 1 week ago vs 1 month ago."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    snapshots = _as_of_offsets(panel.dropna(how="all").index)
    styles = {"Current": "-o", "1 Week Ago": "--s", "1 Month Ago": ":^"}

    for ax, (prefix, title) in zip(axes, (("US", "US Treasury"), ("JP", "JGB"))):
        cols = _curve_points(panel, prefix)
        tenors = [c.replace(prefix, "") for c in cols]
        x = np.arange(len(cols))
        for label, ts in snapshots.items():
            if pd.isna(ts):
                continue
            ax.plot(
                x,
                panel.loc[ts, cols].to_numpy(),
                styles[label],
                label=f"{label} ({ts.date()})",
            )
        ax.set_xticks(x, tenors)
        ax.set_title(f"{title} Curve")
        ax.set_xlabel("Tenor")
        ax.set_ylabel("Yield (%)")
        ax.legend(frameon=True, fontsize=8)
    fig.suptitle("Yield Curve Shifts", fontweight="bold")
    fig.tight_layout()
    return fig


# --------------------------------------------------------------------------- #
# 3. Macro decoupling tracker
# --------------------------------------------------------------------------- #
def _dual_axis(
    ax: Axes,
    left: pd.Series,
    right: pd.Series,
    left_label: str,
    right_label: str,
    *,
    left_color: str = "#1f4e79",
    right_color: str = "#c55a11",
    invert_right: bool = False,
) -> None:
    ax.plot(left.index, left.to_numpy(), color=left_color, lw=1.6, label=left_label)
    ax.set_ylabel(left_label, color=left_color)
    ax.tick_params(axis="y", labelcolor=left_color)
    twin = ax.twinx()
    twin.plot(
        right.index, right.to_numpy(), color=right_color, lw=1.6, label=right_label
    )
    twin.set_ylabel(right_label, color=right_color)
    twin.tick_params(axis="y", labelcolor=right_color)
    twin.grid(False)
    if invert_right:
        twin.invert_yaxis()


def plot_decoupling(panel: pd.DataFrame, *, lookback: int = 504) -> Figure:
    """Dual-axis structural-correlation tracker: real rates/gold & WTI/BEI."""
    enriched = augment(panel).tail(lookback)
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # Real yields (inverted) vs gold: structurally negatively correlated.
    _dual_axis(
        axes[0],
        enriched["US10Y_REAL"],
        enriched["GOLD"],
        "US 10Y Real Yield (%, inverted)",
        "Gold ($/oz)",
        invert_right=False,
        left_color="#1f4e79",
        right_color="#bf9000",
    )
    axes[0].invert_yaxis()
    axes[0].set_title("Real Rates vs Gold")

    # WTI vs breakeven inflation: structurally positively correlated.
    _dual_axis(
        axes[1],
        enriched["WTI"],
        enriched["US10Y_BEI"],
        "WTI Crude ($/bbl)",
        "US 10Y Breakeven (%)",
        left_color="#7030a0",
        right_color="#c55a11",
    )
    axes[1].set_title("WTI Crude vs 10Y Breakeven Inflation")
    axes[1].set_xlabel("Date")

    fig.suptitle("Macro Decoupling Tracker", fontweight="bold")
    fig.tight_layout()
    return fig


def plot_rolling_correlations(
    correlations: pd.DataFrame, *, lookback: int = 504
) -> Figure:
    """Time series of the 30d/60d rolling correlations for macro pairs."""
    data = correlations.tail(lookback)
    fig, ax = plt.subplots(figsize=(12, 4.6))
    for col in data.columns:
        ax.plot(data.index, data[col].to_numpy(), lw=1.3, label=col)
    ax.axhline(0.0, color="black", lw=0.8, alpha=0.6)
    ax.set_ylim(-1.05, 1.05)
    ax.set_title("Rolling Correlations (macro pairs)")
    ax.set_ylabel("Pearson ρ")
    ax.legend(frameon=True, fontsize=8, ncol=2)
    fig.tight_layout()
    return fig


# --------------------------------------------------------------------------- #
# 4. Rates deep-dive: US Treasury & JGB curves
# --------------------------------------------------------------------------- #
_MARKET_TITLE: Final[dict[str, str]] = {"US": "US Treasury", "JP": "JGB"}


def _snapshot_dates(index: pd.DatetimeIndex) -> dict[str, pd.Timestamp]:
    as_of = index.max()
    return {
        "Current": as_of,
        "1W ago": index[index <= as_of - pd.Timedelta(days=7)].max(),
        "1M ago": index[index <= as_of - pd.Timedelta(days=30)].max(),
    }


def plot_curve_snapshot(panel: pd.DataFrame, market: str) -> Figure:
    """Full-curve snapshot (all tenors): current vs 1W vs 1M, plus the WoW shift."""
    curve = CURVES[market]
    tenors = list(curve)
    cols = list(curve.values())
    lvl = panel[cols].dropna(how="all")
    snaps = _snapshot_dates(lvl.index)
    styles = {"Current": "-o", "1W ago": "--s", "1M ago": ":^"}

    fig, (ax, axd) = plt.subplots(2, 1, figsize=(11, 7), height_ratios=[2.2, 1], sharex=True)
    for label, ts in snaps.items():
        if pd.isna(ts):
            continue
        ax.plot(tenors, lvl.loc[ts, cols].to_numpy(), styles[label], label=f"{label} ({ts.date()})")
    ax.set_title(f"{_MARKET_TITLE[market]} Curve")
    ax.set_ylabel("Yield (%)")
    ax.legend(frameon=True, fontsize=9)

    cur, prev = snaps["Current"], snaps["1W ago"]
    if not pd.isna(prev):
        shift = (lvl.loc[cur, cols] - lvl.loc[prev, cols]).to_numpy() * 100.0
        colors = ["#c0392b" if v >= 0 else "#1f4e79" for v in shift]
        axd.bar([str(t) for t in tenors], shift, color=colors, alpha=0.85)
        axd.axhline(0, color="black", lw=0.8)
        axd.set_ylabel("WoW Δ (bp)")
    axd.set_xlabel("Tenor (Y)")
    axd.set_xticks(range(len(tenors)), [str(t) for t in tenors])
    fig.suptitle(f"{_MARKET_TITLE[market]} Curve Snapshot & Weekly Shift", fontweight="bold")
    fig.tight_layout()
    return fig


def plot_rates_heatmap(panel: pd.DataFrame) -> Figure:
    """Slope & butterfly z-score heatmap (momentum + level richness) for US & JP."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 6))
    for ax, market in zip(axes, ("US", "JP")):
        snap = rates_snapshot(panel, market)[["Z_1W", "Z_level"]]
        sns.heatmap(
            snap, annot=True, fmt="+.2f", cmap="RdBu_r", center=0.0, vmin=-3, vmax=3,
            linewidths=0.5, cbar=False, ax=ax,
        )
        ax.set_title(f"{_MARKET_TITLE[market]} slopes & flies")
        ax.set_ylabel("")
    fig.suptitle("Curve Momentum (Z_1W) & Level Richness (Z_level)", fontweight="bold")
    fig.tight_layout()
    return fig


def plot_butterflies(
    panel: pd.DataFrame, market: str, flies: tuple[str, ...], *, lookback: int = 504
) -> Figure:
    """Butterfly time series with mean and ±1σ/±2σ bands over the window."""
    metrics = curve_metrics(panel, market).tail(lookback)
    n = len(flies)
    fig, axes = plt.subplots(n, 1, figsize=(11, 2.6 * n), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, fly in zip(axes, flies):
        s = metrics[fly].dropna()
        mu, sd = s.mean(), s.std(ddof=0)
        ax.plot(s.index, s.to_numpy(), color="#1f4e79", lw=1.3)
        ax.axhline(mu, color="black", lw=0.8, ls="--", alpha=0.7)
        for k, a in ((1, 0.18), (2, 0.10)):
            ax.fill_between(s.index, mu - k * sd, mu + k * sd, color="#1f4e79", alpha=a)
        last, z = s.iloc[-1], (s.iloc[-1] - mu) / sd if sd else 0.0
        ax.set_title(f"{fly}  last={last:+.1f}bp  z={z:+.2f}", fontsize=10)
        ax.set_ylabel("bp")
    fig.suptitle(f"{_MARKET_TITLE[market]} Butterflies (belly cheap = up)", fontweight="bold")
    fig.tight_layout()
    return fig


def plot_curve_pca(panel: pd.DataFrame, market: str, *, lookback: int = 252) -> Figure:
    """PCA loadings (level/slope/curvature), factor history, and rich/cheap bars."""
    pca: PCAResult = curve_pca(panel, market, lookback=lookback)
    tenors = [int(c.lstrip("USJP").rstrip("Y")) for c in pca.loadings.index]
    fig = plt.figure(figsize=(12, 7))
    gs = fig.add_gridspec(2, 2)
    ax_load, ax_rc = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1])
    ax_sc = fig.add_subplot(gs[1, :])

    for pc in pca.loadings.columns:
        ax_load.plot(tenors, pca.loadings[pc].to_numpy(), "-o",
                     label=f"{pc} ({pca.explained[pc]:.0%})")
    ax_load.axhline(0, color="black", lw=0.6)
    ax_load.set_title("Loadings (PC1≈level, PC2≈slope, PC3≈curvature)")
    ax_load.set_xlabel("Tenor (Y)")
    ax_load.legend(fontsize=8)

    rc = pca.rich_cheap
    colors = ["#c0392b" if v >= 0 else "#1f7a3d" for v in rc.to_numpy()]
    ax_rc.bar(range(len(rc)), rc.to_numpy(), color=colors, alpha=0.85)
    ax_rc.axhline(0, color="black", lw=0.8)
    ax_rc.set_xticks(range(len(rc)), list(rc.index), rotation=45, fontsize=8)
    ax_rc.set_title("3-factor residual (bp): + cheap / − rich")

    for pc in pca.scores.columns:
        ax_sc.plot(pca.scores.index, pca.scores[pc].to_numpy(), lw=1.2, label=pc)
    ax_sc.axhline(0, color="black", lw=0.6)
    ax_sc.set_title("PCA factor history")
    ax_sc.legend(fontsize=8, ncol=3)

    fig.suptitle(f"{_MARKET_TITLE[market]} Curve PCA — as of {pca.as_of.date()}", fontweight="bold")
    fig.tight_layout()
    return fig
