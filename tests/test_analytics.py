"""Tests for the deliberate analytics conventions (the subtle, easy-to-break math).

Covers: curve slope sign, tenor-weighted butterfly sign (the 5s10s20s bug fix),
PCA sign-normalization (PC1=level / PC2=slope / PC3=curvature), and the FX
rate-differential regression.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from macro_watch import analytics


def _flat_curve(market: str, yields: dict[int, float], n: int = 10) -> pd.DataFrame:
    """Panel whose curve columns hold the given (constant) yields, in %."""
    cols = analytics.CURVES[market]
    idx = pd.bdate_range("2022-01-03", periods=n)
    return pd.DataFrame({col: float(yields[t]) for t, col in cols.items()}, index=idx)


# --------------------------------------------------------------------------- #
# Slopes
# --------------------------------------------------------------------------- #
def test_slope_is_long_minus_short_in_bp():
    # US2Y=1.0, US10Y=1.5 -> 2s10s = +50 bp (positive = steeper).
    panel = _flat_curve("US", {2: 1.0, 3: 1.2, 5: 1.3, 7: 1.4, 10: 1.5, 20: 1.7, 30: 1.9})
    m = analytics.curve_metrics(panel, "US").iloc[-1]
    assert m["US_2s10s"] == pytest.approx(50.0)
    assert m["US_10s30s"] == pytest.approx(40.0)


def test_inverted_curve_gives_negative_slope():
    panel = _flat_curve("US", {2: 2.0, 3: 1.9, 5: 1.8, 7: 1.7, 10: 1.5, 20: 1.4, 30: 1.3})
    m = analytics.curve_metrics(panel, "US").iloc[-1]
    assert m["US_2s10s"] == pytest.approx(-50.0)


# --------------------------------------------------------------------------- #
# Butterflies — tenor-weighted sign (the documented 5s10s20s fix)
# --------------------------------------------------------------------------- #
def test_tenor_weighted_fly_is_zero_on_a_straight_line():
    # Yield linear in tenor: the belly sits exactly on the wings' interpolation,
    # so a *correct* (tenor-weighted) fly is ~0. The naive 2:1:1 fly is not, for an
    # unevenly-spaced fly like JP 5s10s20s — this is why tenor-weighting exists.
    panel = _flat_curve("JP", {t: 0.1 * t for t in analytics.CURVES["JP"]})
    tenor = analytics.curve_metrics(panel, "JP", fly_weighting="tenor").iloc[-1]
    equal = analytics.curve_metrics(panel, "JP", fly_weighting="equal").iloc[-1]
    assert tenor["JP_5s10s20s"] == pytest.approx(0.0, abs=1e-9)
    assert abs(equal["JP_5s10s20s"]) > 10.0  # bp: naive fly wrongly sees curvature


def test_cheap_belly_is_positive():
    # Lift the 10Y belly above the line -> belly cheap -> positive fly (bp).
    yields = {t: 0.1 * t for t in analytics.CURVES["JP"]}
    yields[10] += 0.2
    panel = _flat_curve("JP", yields)
    fly = analytics.curve_metrics(panel, "JP", fly_weighting="tenor").iloc[-1]
    assert fly["JP_5s10s20s"] == pytest.approx(20.0)  # +20 bp, belly cheap


# --------------------------------------------------------------------------- #
# PCA — sign normalization
# --------------------------------------------------------------------------- #
def test_pca_orients_level_slope_curvature():
    market = "US"
    cols = list(analytics.CURVES[market].values())
    tenors = np.array(list(analytics.CURVES[market]), dtype=float)
    idx = pd.bdate_range("2022-01-03", periods=300)
    rng = np.random.default_rng(1)

    # Three orthonormal curve shapes (level / slope / curvature) with *decreasing*
    # daily variance, so PCA recovers level > slope > curvature in that order.
    # Unit norm matters: an un-normalized quadratic blows up at the long end and
    # would contaminate PC1.
    def _unit(v: np.ndarray) -> np.ndarray:
        return v / np.linalg.norm(v)

    lvl = _unit(np.ones_like(tenors))
    slope = _unit(tenors - tenors.mean())
    curv = (tenors - tenors.mean()) ** 2
    curv = curv - curv.mean()
    curv = _unit(curv - (curv @ slope) * slope)  # orthogonalize vs slope

    X = (
        2.0
        + np.outer(rng.normal(0, 1.0, 300), lvl)
        + np.outer(rng.normal(0, 0.4, 300), slope)
        + np.outer(rng.normal(0, 0.15, 300), curv)
    )
    panel = pd.DataFrame(X, index=idx, columns=cols)
    pca = analytics.curve_pca(panel, market)
    load = pca.loadings

    # PC1 level: all loadings share sign, normalized positive.
    assert load["PC1"].sum() > 0
    assert (load["PC1"] > 0).all()
    # PC2 slope: long end loads above the short end.
    assert load["PC2"].iloc[-1] > load["PC2"].iloc[0]
    # PC3 curvature: belly loads above the wing average.
    mid = len(load) // 2
    assert load["PC3"].iloc[mid] > 0.5 * (load["PC3"].iloc[0] + load["PC3"].iloc[-1])
    # Variance ordering.
    ev = pca.explained
    assert ev["PC1"] >= ev["PC2"] >= ev["PC3"] > 0


def test_pca_rich_cheap_residual_sign():
    # A curve that is exactly a 3-factor combination has ~0 rich/cheap residual.
    market = "JP"
    cols = list(analytics.CURVES[market].values())
    tenors = np.array(list(analytics.CURVES[market]), dtype=float)
    idx = pd.bdate_range("2022-01-03", periods=200)
    rng = np.random.default_rng(2)
    slope = (tenors - tenors.mean()) / tenors.std()
    X = 1.5 + np.outer(rng.normal(0, 1.0, 200), np.ones_like(tenors)) + np.outer(
        rng.normal(0, 0.3, 200), slope
    )
    panel = pd.DataFrame(X, index=idx, columns=cols)
    pca = analytics.curve_pca(panel, market)
    # Two-factor data reconstructed by 3 factors leaves negligible residual.
    assert pca.rich_cheap.abs().max() < 1.0  # bp


# --------------------------------------------------------------------------- #
# FX — rate differential & fair value regression
# --------------------------------------------------------------------------- #
def test_rate_differential_is_us_minus_jp_in_bp():
    idx = pd.bdate_range("2022-01-03", periods=50)
    panel = pd.DataFrame({"US10Y": 4.0, "JP10Y": 1.0}, index=idx)
    diff = analytics.rate_differential(panel, 10)
    assert diff.name == "US10Y-JP10Y"
    assert diff.iloc[-1] == pytest.approx(300.0)  # (4.0 - 1.0) * 100 bp


def test_fx_fairvalue_recovers_structural_beta():
    idx = pd.bdate_range("2018-01-01", periods=1300)
    rng = np.random.default_rng(3)
    diff_bp = np.cumsum(rng.normal(0, 2.0, len(idx))) + 200.0  # differential, bp
    beta_true = 0.05  # yen per bp
    usdjpy = 100.0 + beta_true * diff_bp + rng.normal(0, 0.5, len(idx))
    # rate_differential = (US10Y - JP10Y) * 100; pin JP10Y, back out US10Y in %.
    panel = pd.DataFrame(
        {"USDJPY": usdjpy, "US10Y": 1.0 + diff_bp / 100.0, "JP10Y": 1.0}, index=idx
    )
    fv = analytics.fx_rate_fairvalue(panel, "USDJPY", tenor=10, lookback=1260)
    assert fv.driver == "US10Y-JP10Y"
    assert fv.beta == pytest.approx(beta_true, rel=0.1)
    assert fv.r2 > 0.9
    # residual is actual - fitted, so it sums to ~0 over the fit window.
    assert abs(float(fv.residual.mean())) < 0.1
