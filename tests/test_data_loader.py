"""Tests for the MoF JGB Japanese-era date parsing (Shift-JIS CSV quirk)."""

from __future__ import annotations

import pandas as pd
import pytest

from macro_watch.data_loader import DataSourceError, _parse_jgb_dates


def _parse_one(token: str) -> pd.Timestamp:
    return _parse_jgb_dates(pd.Series([token]))[0]


def test_reiwa_offset_matches_spec_example():
    # CLAUDE.md: R8.6.1 = Reiwa 8 = 2026-06-01 (Reiwa 1 = 2019).
    assert _parse_one("R8.6.1") == pd.Timestamp("2026-06-01")
    assert _parse_one("R1.5.1") == pd.Timestamp("2019-05-01")


def test_each_era_offset():
    cases = {
        "M1.1.1": pd.Timestamp("1868-01-01"),  # Meiji 1
        "T1.7.30": pd.Timestamp("1912-07-30"),  # Taisho 1
        "S49.9.24": pd.Timestamp("1974-09-24"),  # Showa 49
        "H1.1.8": pd.Timestamp("1989-01-08"),  # Heisei 1
        "R6.4.1": pd.Timestamp("2024-04-01"),  # Reiwa 6
    }
    for token, expected in cases.items():
        assert _parse_one(token) == expected, token


def test_handles_one_and_two_digit_month_day_and_whitespace():
    assert _parse_one("R8.6.1") == pd.Timestamp("2026-06-01")
    assert _parse_one("R8.06.01") == pd.Timestamp("2026-06-01")
    assert _parse_one("  R8.12.31  ") == pd.Timestamp("2026-12-31")


def test_vectorized_parse_preserves_order():
    idx = _parse_jgb_dates(pd.Series(["S49.9.24", "H1.1.8", "R8.6.1"]))
    assert list(idx) == [
        pd.Timestamp("1974-09-24"),
        pd.Timestamp("1989-01-08"),
        pd.Timestamp("2026-06-01"),
    ]


def test_unknown_era_token_raises():
    with pytest.raises(DataSourceError, match="era token"):
        _parse_jgb_dates(pd.Series(["X3.1.1"]))
