"""Ingestion, alignment and Parquet caching for cross-asset macro data.

Sources
-------
* MoF Japan  : JGB constant-maturity yields (Shift-JIS CSV, Japanese-era dates).
* FRED       : US rates / breakevens / commodities (keyless via pandas-datareader).
* Yahoo      : equity indices (yfinance, adjusted close).
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Final, Mapping

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger("macro_watch.data_loader")

# --------------------------------------------------------------------------- #
# Source definitions
# --------------------------------------------------------------------------- #
# Spec URL (current month only); the historical sibling shares the exact same
# schema and is used by default so rolling statistics have sufficient lookback.
JGB_CSV_URL: Final[str] = "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"
JGB_HISTORICAL_CSV_URL: Final[str] = (
    "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv"
)

# MoF column label (Japanese) -> canonical name.
JGB_TENOR_MAP: Final[Mapping[str, str]] = {
    "2年": "JP2Y",
    "5年": "JP5Y",
    "10年": "JP10Y",
}

# FRED keyless CSV endpoint (no API key required).
FRED_CSV_URL: Final[str] = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# FRED series id -> canonical name.
# NOTE: the spec's London Gold Fix series ``GOLDAMGBD228NLBM`` was discontinued
# and de-listed by FRED (HTTP 404), so gold is sourced from Yahoo (GC=F) below.
FRED_SERIES_MAP: Final[Mapping[str, str]] = {
    "DGS2": "US2Y",
    "DGS10": "US10Y",
    "T10YIE": "US10Y_BEI",
    "DCOILWTICO": "WTI",
}
DISCONTINUED_GOLD_SERIES: Final[str] = "GOLDAMGBD228NLBM"

# Yahoo ticker -> canonical name. GC=F (COMEX gold front month) provides the
# current/continuous gold price that the de-listed FRED fix no longer offers.
YAHOO_TICKER_MAP: Final[Mapping[str, str]] = {
    "^GSPC": "SPX",
    "^IXIC": "NDX",
    "^N225": "N225",
    "^TOPX": "TOPIX",
    "GC=F": "GOLD",
}

# Deterministic schema: order matters for Parquet validation.
RATE_COLUMNS: Final[tuple[str, ...]] = (
    "US2Y",
    "US10Y",
    "US10Y_BEI",
    "JP2Y",
    "JP5Y",
    "JP10Y",
)
COMMODITY_COLUMNS: Final[tuple[str, ...]] = ("WTI", "GOLD")
EQUITY_COLUMNS: Final[tuple[str, ...]] = ("SPX", "NDX", "N225", "TOPIX")
CANONICAL_COLUMNS: Final[tuple[str, ...]] = (
    RATE_COLUMNS + COMMODITY_COLUMNS + EQUITY_COLUMNS
)

# Japanese era -> (Gregorian year of era-year 1) minus 1, i.e. offset.
_ERA_OFFSET: Final[Mapping[str, int]] = {
    "M": 1867,  # Meiji 1 = 1868
    "T": 1911,  # Taisho 1 = 1912
    "S": 1925,  # Showa 1 = 1926
    "H": 1988,  # Heisei 1 = 1989
    "R": 2018,  # Reiwa 1 = 2019
}


class DataSourceError(RuntimeError):
    """Raised when a remote source is unreachable or structurally invalid."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _get_with_retry(
    url: str,
    *,
    timeout: int,
    retries: int = 4,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    """GET with bounded retries on transient network errors / 5xx."""
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                url, params=params, headers=headers, timeout=(10, timeout)
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last = exc
            logger.warning(
                "GET %s failed (attempt %d/%d): %s", url, attempt, retries, exc
            )
    raise DataSourceError(f"GET {url} failed after {retries} attempts: {last}")


def _strip_tz(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return a timezone-naive, normalized (midnight) DatetimeIndex."""
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


def _parse_jgb_dates(raw: pd.Series) -> pd.DatetimeIndex:
    """Vectorized parse of MoF Japanese-era dates ('R8.6.1', 'S49.9.24')."""
    parts = raw.astype(str).str.extract(r"^\s*([MTSHR])(\d+)\.(\d{1,2})\.(\d{1,2})\s*$")
    parts.columns = ["era", "yy", "mm", "dd"]
    offset = parts["era"].map(_ERA_OFFSET)
    if offset.isna().any():
        bad = raw[offset.isna()].head(3).tolist()
        raise DataSourceError(f"Unrecognized JGB era token(s): {bad}")
    year = offset.astype("int64") + parts["yy"].astype("int64")
    frame = pd.DataFrame(
        {
            "year": year,
            "month": parts["mm"].astype("int64"),
            "day": parts["dd"].astype("int64"),
        }
    )
    return pd.DatetimeIndex(pd.to_datetime(frame))


# --------------------------------------------------------------------------- #
# Per-source loaders
# --------------------------------------------------------------------------- #
def _fetch_jgb_csv(url: str, *, timeout: int) -> pd.DataFrame:
    """Download and parse a single MoF JGB CSV (historical or current-month)."""
    resp = _get_with_retry(url, timeout=timeout)

    if resp.content[:15].lstrip().startswith(b"<!DOCTYPE"):
        raise DataSourceError(f"MoF JGB endpoint returned HTML, not CSV: {url}")

    text = resp.content.decode("shift_jis", errors="replace")
    try:
        # Row 0 is a title banner; row 1 holds the tenor header.
        frame = pd.read_csv(io.StringIO(text), header=1, dtype=str)
    except (pd.errors.ParserError, ValueError) as exc:
        raise DataSourceError(f"MoF JGB CSV parse error ({url}): {exc}") from exc

    date_col = frame.columns[0]
    missing = [c for c in JGB_TENOR_MAP if c not in frame.columns]
    if missing:
        raise DataSourceError(
            f"MoF JGB CSV schema changed; missing tenor columns {missing}. "
            f"Got columns: {list(frame.columns)[:8]}"
        )

    frame = frame[frame[date_col].astype(str).str.match(r"^[MTSHR]\d")]
    if frame.empty:
        raise DataSourceError(f"MoF JGB CSV contained no parseable data rows ({url}).")

    out = pd.DataFrame(index=_parse_jgb_dates(frame[date_col]))
    for jp_label, canonical in JGB_TENOR_MAP.items():
        col = frame[jp_label].replace("-", np.nan)
        out[canonical] = pd.to_numeric(col, errors="coerce").to_numpy()
    out.index = _strip_tz(pd.DatetimeIndex(out.index))
    return out


def load_jgb(
    urls: tuple[str, ...] = (JGB_HISTORICAL_CSV_URL, JGB_CSV_URL), *, timeout: int = 60
) -> pd.DataFrame:
    """Parse MoF JGB yields into JP2Y/JP5Y/JP10Y.

    By default the long historical file is combined with the spec's current-month
    file (``jgbcm.csv``) so the latest sessions are present without stale ffill.
    Raises only if *every* source fails.
    """
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    for url in urls:
        try:
            frames.append(_fetch_jgb_csv(url, timeout=timeout))
        except DataSourceError as exc:
            errors.append(str(exc))
            logger.warning("JGB source skipped: %s", exc)
    if not frames:
        raise DataSourceError(f"All MoF JGB sources failed: {errors}")

    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    logger.info(
        "JGB: %d rows (%s -> %s)",
        len(out),
        out.index.min().date(),
        out.index.max().date(),
    )
    return out


def load_fred(
    start: date,
    end: date,
    series: Mapping[str, str] = FRED_SERIES_MAP,
    *,
    timeout: int = 60,
) -> pd.DataFrame:
    """Fetch FRED series via the keyless ``fredgraph.csv`` endpoint."""
    params = {
        "id": ",".join(series),
        "cosd": start.isoformat(),
        "coed": end.isoformat(),
    }
    resp = _get_with_retry(
        FRED_CSV_URL,
        timeout=timeout,
        params=params,
        headers={"User-Agent": "macro_watch/0.1 (+https://fred.stlouisfed.org)"},
    )

    try:
        raw = pd.read_csv(io.StringIO(resp.text))
    except (pd.errors.ParserError, ValueError) as exc:
        raise DataSourceError(f"FRED CSV parse error: {exc}") from exc

    date_col = raw.columns[0]  # 'observation_date' (or legacy 'DATE')
    raw = raw.set_index(pd.to_datetime(raw[date_col], errors="coerce")).drop(
        columns=date_col
    )
    raw.index = _strip_tz(pd.DatetimeIndex(raw.index))

    # FRED silently omits de-listed ids; rename what came back and warn on gaps.
    present = {sid: name for sid, name in series.items() if sid in raw.columns}
    missing = [sid for sid in series if sid not in raw.columns]
    if missing:
        logger.warning("FRED omitted series (de-listed/unavailable): %s", missing)
    if not present:
        raise DataSourceError("FRED returned none of the requested series.")

    out = raw[list(present)].rename(columns=present)
    out = out.replace(".", np.nan).apply(pd.to_numeric, errors="coerce")
    logger.info("FRED: %d rows, cols=%s", len(out), list(out.columns))
    return out


def load_yahoo(
    start: date, end: date, tickers: Mapping[str, str] = YAHOO_TICKER_MAP
) -> pd.DataFrame:
    """Fetch adjusted-close equity-index series via yfinance."""
    import yfinance as yf  # lazy import

    try:
        raw = yf.download(
            list(tickers),
            start=start,
            end=end,
            auto_adjust=False,
            progress=False,
            group_by="column",
            threads=True,
        )
    except Exception as exc:
        raise DataSourceError(f"Yahoo Finance download failed: {exc}") from exc

    if raw is None or raw.empty:
        raise DataSourceError("Yahoo Finance returned an empty frame.")

    # Prefer adjusted close; fall back to close if auto-adjust collapsed it.
    field = "Adj Close" if "Adj Close" in raw.columns.get_level_values(0) else "Close"
    prices = raw[field].copy()
    if isinstance(prices, pd.Series):  # single ticker degenerate case
        prices = prices.to_frame(name=list(tickers)[0])

    prices = prices.rename(columns=dict(tickers))
    prices.index = _strip_tz(pd.DatetimeIndex(prices.index))
    prices = prices.apply(pd.to_numeric, errors="coerce")
    logger.info("Yahoo: %d rows, cols=%s", len(prices), list(prices.columns))
    return prices


# --------------------------------------------------------------------------- #
# Alignment
# --------------------------------------------------------------------------- #
def align_frames(frames: list[pd.DataFrame], *, ffill: bool = True) -> pd.DataFrame:
    """Outer-join sources onto a continuous business-day index and forward-fill."""
    present = [f for f in frames if f is not None and not f.empty]
    if not present:
        raise DataSourceError("No data frames available to align.")

    merged = pd.concat(present, axis=1, join="outer").sort_index()
    merged = merged.loc[:, [c for c in CANONICAL_COLUMNS if c in merged.columns]]

    bday_index = pd.bdate_range(merged.index.min(), merged.index.max(), name="date")
    merged = merged.reindex(bday_index)
    if ffill:
        merged = merged.ffill()

    for col in CANONICAL_COLUMNS:  # guarantee deterministic schema
        if col not in merged.columns:
            merged[col] = np.nan
    return merged[list(CANONICAL_COLUMNS)]


# --------------------------------------------------------------------------- #
# Orchestrating loader with Parquet cache
# --------------------------------------------------------------------------- #
@dataclass
class MacroDataLoader:
    """Fetch, align, validate and cache the full cross-asset panel."""

    cache_dir: Path = field(default_factory=lambda: Path("data_cache"))
    start: date = date(2015, 1, 1)
    end: date | None = None
    jgb_url: str = JGB_HISTORICAL_CSV_URL
    compression: str = "snappy"

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cache_path(self) -> Path:
        return self.cache_dir / "macro_panel.parquet"

    @property
    def _resolved_end(self) -> date:
        return self.end or datetime.now().date()

    # -- fetch ------------------------------------------------------------- #
    def fetch(self) -> pd.DataFrame:
        """Pull every source (degrading gracefully) and align the panel."""
        frames: list[pd.DataFrame] = []
        for name, loader in (
            ("JGB", lambda: load_jgb(self.jgb_url)),
            ("FRED", lambda: load_fred(self.start, self._resolved_end)),
            ("Yahoo", lambda: load_yahoo(self.start, self._resolved_end)),
        ):
            try:
                frames.append(loader())
            except DataSourceError as exc:
                logger.warning("Source %s unavailable, skipping: %s", name, exc)
        return align_frames(frames)

    # -- cache I/O --------------------------------------------------------- #
    def _validate_schema(self, frame: pd.DataFrame) -> bool:
        return list(frame.columns) == list(CANONICAL_COLUMNS) and isinstance(
            frame.index, pd.DatetimeIndex
        )

    def save(self, frame: pd.DataFrame) -> Path:
        if not self._validate_schema(frame):
            raise DataSourceError("Refusing to cache frame with non-canonical schema.")
        frame.to_parquet(self.cache_path, compression=self.compression, index=True)
        logger.info("Cached panel -> %s (%d rows)", self.cache_path, len(frame))
        return self.cache_path

    def load_cache(self) -> pd.DataFrame | None:
        if not self.cache_path.exists():
            return None
        try:
            frame = pd.read_parquet(self.cache_path)
        except Exception as exc:  # noqa: BLE001 - corrupt cache -> refetch
            logger.warning("Cache unreadable (%s); will refetch.", exc)
            return None
        frame.index = _strip_tz(pd.DatetimeIndex(frame.index))
        if not self._validate_schema(frame):
            logger.warning("Cached schema mismatch; will refetch.")
            return None
        return frame

    # -- public API -------------------------------------------------------- #
    def update(self) -> pd.DataFrame:
        """Force a fresh fetch and overwrite the cache."""
        frame = self.fetch()
        self.save(frame)
        return frame

    def load(self, *, refresh: bool = False) -> pd.DataFrame:
        """Return the panel, using the cache unless ``refresh`` is requested."""
        if not refresh:
            cached = self.load_cache()
            if cached is not None:
                return cached
        return self.update()
