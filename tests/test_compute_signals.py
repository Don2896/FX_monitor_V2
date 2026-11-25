from __future__ import annotations

import math

import pandas as pd
import pytest

from src.compute_signals import compute_signals


# ── Helpers ───────────────────────────────────────────────────────────────────

def _latest(df_signals: pd.DataFrame, pair: str) -> pd.Series:
    """Return the last (most recent) row for a given pair."""
    return (
        df_signals[df_signals["pair"] == pair]
        .sort_values("timestamp_utc")
        .iloc[-1]
    )


def _oldest(df_signals: pd.DataFrame, pair: str) -> pd.Series:
    return (
        df_signals[df_signals["pair"] == pair]
        .sort_values("timestamp_utc")
        .iloc[0]
    )


# ── Signal column presence ────────────────────────────────────────────────────

def test_signal_columns_added(fx_history_df):
    result = compute_signals(fx_history_df)
    for col in ("pct_change_1run", "pct_change_60m", "pct_change_24h"):
        assert col in result.columns


def test_row_count_preserved(fx_history_df):
    result = compute_signals(fx_history_df)
    assert len(result) == len(fx_history_df)


# ── First-row edge cases (no prior observation) ───────────────────────────────

def test_oldest_row_pct_1run_is_nan(fx_history_df):
    result = compute_signals(fx_history_df)
    assert math.isnan(_oldest(result, "EURUSD")["pct_change_1run"])
    assert math.isnan(_oldest(result, "XAUUSD")["pct_change_1run"])


def test_oldest_row_pct_60m_is_nan(fx_history_df):
    result = compute_signals(fx_history_df)
    assert math.isnan(_oldest(result, "EURUSD")["pct_change_60m"])


def test_oldest_row_pct_24h_is_nan(fx_history_df):
    result = compute_signals(fx_history_df)
    assert math.isnan(_oldest(result, "EURUSD")["pct_change_24h"])


# ── pct_change_1run values ────────────────────────────────────────────────────

def test_pct_change_1run_eurusd(fx_history_df):
    # latest rate=1.0900, previous=1.0880 → (1.09/1.088 - 1)*100 ≈ 0.1838%
    result = compute_signals(fx_history_df)
    row = _latest(result, "EURUSD")
    expected = (1.0900 / 1.0880 - 1.0) * 100.0
    assert abs(row["pct_change_1run"] - expected) < 1e-4


def test_pct_change_1run_xauusd(fx_history_df):
    # latest rate=2900, previous=2880 → (2900/2880 - 1)*100 ≈ 0.6944%
    result = compute_signals(fx_history_df)
    row = _latest(result, "XAUUSD")
    expected = (2900.0 / 2880.0 - 1.0) * 100.0
    assert abs(row["pct_change_1run"] - expected) < 1e-4


# ── pct_change_60m values ─────────────────────────────────────────────────────

def test_pct_change_60m_eurusd_uses_65min_baseline(fx_history_df):
    # target_time = ts(5min) - 60min = ts(65min) → exact match → ref_rate=1.0880
    result = compute_signals(fx_history_df)
    row = _latest(result, "EURUSD")
    expected = (1.0900 / 1.0880 - 1.0) * 100.0
    assert abs(row["pct_change_60m"] - expected) < 1e-4


def test_pct_change_60m_xauusd_uses_65min_baseline(fx_history_df):
    result = compute_signals(fx_history_df)
    row = _latest(result, "XAUUSD")
    expected = (2900.0 / 2880.0 - 1.0) * 100.0
    assert abs(row["pct_change_60m"] - expected) < 1e-4


# ── pct_change_24h values ─────────────────────────────────────────────────────

def test_pct_change_24h_eurusd_uses_1500min_baseline(fx_history_df):
    # target_time = ts(5min) - 24h = ts(1445min) → nearest prior = ts(1500min) → ref_rate=1.0850
    result = compute_signals(fx_history_df)
    row = _latest(result, "EURUSD")
    expected = (1.0900 / 1.0850 - 1.0) * 100.0
    assert abs(row["pct_change_24h"] - expected) < 1e-4


def test_pct_change_24h_xauusd_uses_1500min_baseline(fx_history_df):
    result = compute_signals(fx_history_df)
    row = _latest(result, "XAUUSD")
    expected = (2900.0 / 2850.0 - 1.0) * 100.0
    assert abs(row["pct_change_24h"] - expected) < 1e-4


# ── Per-pair isolation ────────────────────────────────────────────────────────

def test_signals_isolated_per_pair(fx_history_df):
    # EURUSD and XAUUSD signals must be computed independently
    result = compute_signals(fx_history_df)
    eur_1run = _latest(result, "EURUSD")["pct_change_1run"]
    xau_1run = _latest(result, "XAUUSD")["pct_change_1run"]
    assert abs(eur_1run - xau_1run) > 0.1  # values differ — no cross-contamination


# ── Empty and single-row edge cases ──────────────────────────────────────────

def test_empty_input_returns_empty():
    df = pd.DataFrame(columns=["timestamp_utc", "pair", "base", "quote", "rate", "source"])
    result = compute_signals(df)
    assert result.empty


def test_single_row_all_signals_nan():
    df = pd.DataFrame([{
        "timestamp_utc": "2026-01-01 12:00:00+00:00",
        "pair": "EURUSD", "base": "EUR", "quote": "USD",
        "rate": 1.08, "source": "test",
    }])
    result = compute_signals(df)
    assert len(result) == 1
    assert math.isnan(result.iloc[0]["pct_change_1run"])
    assert math.isnan(result.iloc[0]["pct_change_60m"])
    assert math.isnan(result.iloc[0]["pct_change_24h"])


def test_bad_rate_row_dropped():
    df = pd.DataFrame([
        {"timestamp_utc": "2026-01-01 11:00:00+00:00", "pair": "EURUSD", "base": "EUR", "quote": "USD", "rate": 1.08, "source": "test"},
        {"timestamp_utc": "2026-01-01 12:00:00+00:00", "pair": "EURUSD", "base": "EUR", "quote": "USD", "rate": None, "source": "test"},
    ])
    result = compute_signals(df)
    assert len(result) == 1
