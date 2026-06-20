"""Production-quality plots for the weekly macro brief."""

from __future__ import annotations

from typing import Final

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from macro_watch.analytics import augment, weekly_zscore_matrix

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
            ax.plot(x, panel.loc[ts, cols].to_numpy(), styles[label], label=f"{label} ({ts.date()})")
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
    twin.plot(right.index, right.to_numpy(), color=right_color, lw=1.6, label=right_label)
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


def plot_rolling_correlations(correlations: pd.DataFrame, *, lookback: int = 504) -> Figure:
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
