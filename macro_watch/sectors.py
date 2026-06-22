"""Equity sector attribution for the S&P 500 and Nikkei 225 (web view).

Decomposes each index's recent move into sector contributions
(``contribution = weight x sector_return``), so the bars approximately sum to the
index return. Sector proxies are liquid sector ETFs from Yahoo:

* **S&P 500** -> the 11 SPDR Select Sector ETFs (XLK, XLF, ...), which map 1:1 to
  the GICS sectors.
* **Nikkei 225** -> the 17 NEXT FUNDS TOPIX-17 ETFs (1617.T-1633.T). The Nikkei
  225 has no free sector decomposition, so these TOPIX-17 sectors are used as the
  Japan equity sector backdrop (they track TOPIX, not the N225 exactly).

Index sector **weights** have no clean free live feed, so each market uses a
documented, dated static weight vector (normalized to 1). Weights drift slowly
(a few % per quarter); treat the contribution split as approximate. Sector ETF
prices are cached separately from the canonical panel
(``data_cache/sector_panel.parquet``) so they never touch ``CANONICAL_COLUMNS``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Mapping

import numpy as np
import pandas as pd

from macro_watch.data_loader import DataSourceError, _strip_tz

logger = logging.getLogger("macro_watch.sectors")

WEEK: Final[int] = 5
MONTH: Final[int] = 20
PRICE_TAIL: Final[int] = 504  # sessions of index-price history for the web chart

# Static index sector weights as of ~2026-Q1 (approximate, normalized below).
WEIGHTS_AS_OF: Final[str] = "2026-01-31 (approx., static)"


@dataclass(frozen=True)
class SectorSpec:
    name: str  # sector display name
    ticker: str  # Yahoo proxy ETF
    weight: float  # approximate index weight (un-normalized)


@dataclass(frozen=True)
class IndexSpec:
    index_label: str  # display name
    index_col: str  # canonical panel column for the index level
    sectors: tuple[SectorSpec, ...]
    note: str = ""


# S&P 500 -> SPDR Select Sector ETFs (GICS). Weights ~ Q1-2026 GICS sector weights.
SP500: Final[IndexSpec] = IndexSpec(
    index_label="S&P 500",
    index_col="SPX",
    sectors=(
        SectorSpec("Information Technology", "XLK", 32.0),
        SectorSpec("Financials", "XLF", 13.0),
        SectorSpec("Consumer Discretionary", "XLY", 10.5),
        SectorSpec("Health Care", "XLV", 10.0),
        SectorSpec("Communication Services", "XLC", 9.5),
        SectorSpec("Industrials", "XLI", 8.5),
        SectorSpec("Consumer Staples", "XLP", 5.5),
        SectorSpec("Energy", "XLE", 3.5),
        SectorSpec("Utilities", "XLU", 2.5),
        SectorSpec("Materials", "XLB", 2.0),
        SectorSpec("Real Estate", "XLRE", 2.0),
    ),
)

# Nikkei 225 -> NEXT FUNDS TOPIX-17 ETFs. Weights ~ TOPIX-17 sector weights.
NIKKEI225: Final[IndexSpec] = IndexSpec(
    index_label="Nikkei 225",
    index_col="N225",
    note="Sectors track TOPIX-17, not the Nikkei 225 exactly (no free N225 sector data).",
    sectors=(
        SectorSpec("Electric Appliances & Precision", "1625.T", 17.0),
        SectorSpec("Automobiles & Transport Equip.", "1622.T", 12.0),
        SectorSpec("IT & Services, Others", "1626.T", 12.0),
        SectorSpec("Banks", "1631.T", 7.0),
        SectorSpec("Machinery", "1624.T", 7.0),
        SectorSpec("Commercial & Wholesale Trade", "1629.T", 7.0),
        SectorSpec("Raw Materials & Chemicals", "1620.T", 7.0),
        SectorSpec("Pharmaceutical", "1621.T", 5.0),
        SectorSpec("Financials (ex Banks)", "1632.T", 5.0),
        SectorSpec("Retail Trade", "1630.T", 5.0),
        SectorSpec("Food", "1617.T", 4.0),
        SectorSpec("Construction & Materials", "1619.T", 4.0),
        SectorSpec("Steel & Nonferrous Metals", "1623.T", 3.0),
        SectorSpec("Transportation & Logistics", "1628.T", 3.0),
        SectorSpec("Real Estate", "1633.T", 3.0),
        SectorSpec("Electric Power & Gas", "1627.T", 2.0),
        SectorSpec("Energy Resources", "1618.T", 1.0),
    ),
)

INDICES: Final[Mapping[str, IndexSpec]] = {"SP500": SP500, "Nikkei225": NIKKEI225}


def _all_tickers() -> list[str]:
    seen: dict[str, None] = {}
    for spec in INDICES.values():
        for s in spec.sectors:
            seen.setdefault(s.ticker, None)
    return list(seen)


# --------------------------------------------------------------------------- #
# Price fetch + cache (independent of the canonical panel)
# --------------------------------------------------------------------------- #
@dataclass
class SectorPrices:
    """Fetch/cache sector-ETF prices on a business-day grid (ffilled)."""

    cache_dir: Path = field(default_factory=lambda: Path("data_cache"))
    start: date = date(2023, 1, 1)
    end: date | None = None

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cache_path(self) -> Path:
        return self.cache_dir / "sector_panel.parquet"

    def _fetch(self) -> pd.DataFrame:
        import yfinance as yf  # lazy import

        tickers = _all_tickers()
        raw = yf.download(
            tickers,
            start=self.start,
            # yfinance end is exclusive; +1d so today's just-closed bar is kept.
            end=(self.end or datetime.now().date()) + timedelta(days=1),
            auto_adjust=False,
            progress=False,
            group_by="column",
            threads=True,
        )
        if raw is None or raw.empty:
            raise DataSourceError("Yahoo returned no sector-ETF data.")
        field_ = (
            "Adj Close" if "Adj Close" in raw.columns.get_level_values(0) else "Close"
        )
        px = raw[field_].copy()
        if isinstance(px, pd.Series):
            px = px.to_frame(name=tickers[0])
        px.index = _strip_tz(pd.DatetimeIndex(px.index))
        px = px.apply(pd.to_numeric, errors="coerce")
        bday = pd.bdate_range(px.index.min(), px.index.max(), name="date")
        px = px.reindex(bday).ffill()
        missing = [t for t in tickers if t not in px.columns]
        if missing:
            logger.warning("Sector ETFs missing from Yahoo: %s", missing)
        return px

    def load(self, *, refresh: bool = False) -> pd.DataFrame:
        if not refresh and self.cache_path.exists():
            try:
                px = pd.read_parquet(self.cache_path)
                px.index = _strip_tz(pd.DatetimeIndex(px.index))
                return px
            except Exception as exc:  # noqa: BLE001 - corrupt cache -> refetch
                logger.warning("Sector cache unreadable (%s); refetching.", exc)
        px = self._fetch()
        px.to_parquet(self.cache_path, index=True)
        logger.info("Cached sector prices -> %s (%d rows)", self.cache_path, len(px))
        return px


# --------------------------------------------------------------------------- #
# Attribution
# --------------------------------------------------------------------------- #
def _pct_change(series: pd.Series, n: int) -> float:
    s = series.dropna()
    if len(s) <= n or s.iloc[-1 - n] == 0:
        return float("nan")
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1.0)


def _index_attribution(
    spec: IndexSpec, panel: pd.DataFrame, prices: pd.DataFrame
) -> dict[str, Any]:
    """Per-sector return + weight x return contribution at WoW and 1M horizons."""
    total_w = sum(s.weight for s in spec.sectors)
    index_px = panel[spec.index_col].dropna()
    as_of = index_px.index.max()

    sectors: list[dict[str, Any]] = []
    for s in spec.sectors:
        w = s.weight / total_w
        px = prices[s.ticker] if s.ticker in prices.columns else pd.Series(dtype=float)
        r_w, r_m = _pct_change(px, WEEK), _pct_change(px, MONTH)
        sectors.append(
            {
                "sector": s.name,
                "ticker": s.ticker,
                "weight": w,
                "ret_wow": None if np.isnan(r_w) else r_w * 100.0,
                "ret_1m": None if np.isnan(r_m) else r_m * 100.0,
                "contrib_wow": None if np.isnan(r_w) else w * r_w * 100.0,
                "contrib_1m": None if np.isnan(r_m) else w * r_m * 100.0,
            }
        )

    def _sum(key: str) -> float:
        return float(sum(s[key] for s in sectors if s[key] is not None))

    history = index_px.tail(PRICE_TAIL)
    return {
        "index_label": spec.index_label,
        "as_of": as_of.date().isoformat(),
        "level": float(index_px.iloc[-1]),
        "index_wow": _pct_change(index_px, WEEK) * 100.0,
        "index_1m": _pct_change(index_px, MONTH) * 100.0,
        "prices": [
            {"date": d.date().isoformat(), "value": float(v)}
            for d, v in history.items()
        ],
        "weights_as_of": WEIGHTS_AS_OF,
        "note": spec.note,
        "sectors": sorted(
            sectors, key=lambda d: (d["contrib_wow"] is None, -(d["contrib_wow"] or 0))
        ),
        "reconciliation": {
            "sum_contrib_wow": _sum("contrib_wow"),
            "sum_contrib_1m": _sum("contrib_1m"),
        },
    }


def build_equities(panel: pd.DataFrame, *, refresh: bool = False) -> dict[str, Any]:
    """Equities payload: sector attribution per index, degrading gracefully.

    On a sector-fetch failure the indices still report their own level/returns
    (from the canonical panel) with an empty sector list and an ``error`` note.
    """
    try:
        prices = SectorPrices().load(refresh=refresh)
    except (DataSourceError, Exception) as exc:  # noqa: BLE001 - graceful degrade
        logger.warning("Sector prices unavailable: %s", exc)
        prices = pd.DataFrame()

    out: dict[str, Any] = {}
    for key, spec in INDICES.items():
        attribution = _index_attribution(spec, panel, prices)
        if prices.empty:
            attribution["error"] = "Sector ETF data unavailable; index level only."
        out[key] = attribution
    return out
