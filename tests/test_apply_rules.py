from __future__ import annotations

import math

import pandas as pd
import pytest

from src.rules import apply_rules


# ── Breach column presence ────────────────────────────────────────────────────

def test_breach_columns_added(latest_signals_df, pairs_cfg):
    result = apply_rules(latest_signals_df, pairs_cfg)
    for col in ("breach_1run", "breach_60m", "breach_24h"):
        assert col in result.columns


def test_row_count_preserved(latest_signals_df, pairs_cfg):
    result = apply_rules(latest_signals_df, pairs_cfg)
    assert len(result) == len(latest_signals_df)


# ── EURUSD expected breaches ──────────────────────────────────────────────────
# pct_1run ≈ 0.184% > 0.10 threshold → breach
# pct_60m  ≈ 0.184% > 0.15 threshold → breach
# pct_24h  ≈ 0.461% > 0.40 threshold → breach

def test_eurusd_breach_1run(ruled_df):
    row = ruled_df[ruled_df["pair"] == "EURUSD"].iloc[0]
    assert row["breach_1run"] is True or row["breach_1run"] == True


def test_eurusd_breach_60m(ruled_df):
    row = ruled_df[ruled_df["pair"] == "EURUSD"].iloc[0]
    assert row["breach_60m"] is True or row["breach_60m"] == True


def test_eurusd_breach_24h(ruled_df):
    row = ruled_df[ruled_df["pair"] == "EURUSD"].iloc[0]
    assert row["breach_24h"] is True or row["breach_24h"] == True


# ── XAUUSD expected breaches ──────────────────────────────────────────────────
# pct_1run ≈ 0.694% > 0.40 threshold → breach
# pct_60m  ≈ 0.694% < 0.80 threshold → no breach
# pct_24h  ≈ 1.754% > 1.50 threshold → breach

def test_xauusd_breach_1run(ruled_df):
    row = ruled_df[ruled_df["pair"] == "XAUUSD"].iloc[0]
    assert row["breach_1run"] is True or row["breach_1run"] == True


def test_xauusd_no_breach_60m(ruled_df):
    row = ruled_df[ruled_df["pair"] == "XAUUSD"].iloc[0]
    assert not row["breach_60m"]


def test_xauusd_breach_24h(ruled_df):
    row = ruled_df[ruled_df["pair"] == "XAUUSD"].iloc[0]
    assert row["breach_24h"] is True or row["breach_24h"] == True


# ── NaN signals never breach ──────────────────────────────────────────────────

def test_nan_signals_do_not_breach(pairs_cfg):
    df = pd.DataFrame([{
        "pair": "EURUSD", "rate": 1.08,
        "pct_change_1run": float("nan"),
        "pct_change_60m":  float("nan"),
        "pct_change_24h":  float("nan"),
    }])
    result = apply_rules(df, pairs_cfg)
    assert not result["breach_1run"].iloc[0]
    assert not result["breach_60m"].iloc[0]
    assert not result["breach_24h"].iloc[0]


# ── Unknown pair never breaches ───────────────────────────────────────────────

def test_unknown_pair_never_breaches(pairs_cfg):
    df = pd.DataFrame([{
        "pair": "UNKNOWN", "rate": 1.00,
        "pct_change_1run": 99.0,
        "pct_change_60m":  99.0,
        "pct_change_24h":  99.0,
    }])
    result = apply_rules(df, pairs_cfg)
    assert not result["breach_1run"].iloc[0]
    assert not result["breach_60m"].iloc[0]
    assert not result["breach_24h"].iloc[0]


# ── Empty input ───────────────────────────────────────────────────────────────

def test_empty_dataframe_returns_empty(pairs_cfg):
    df = pd.DataFrame(columns=["pair", "rate", "pct_change_1run", "pct_change_60m", "pct_change_24h"])
    result = apply_rules(df, pairs_cfg)
    assert result.empty


# ── Pair with no thresholds configured ───────────────────────────────────────

def test_pair_missing_threshold_never_breaches():
    cfg = [{"name": "EURUSD", "base": "EUR", "quote": "USD"}]  # no thresholds key
    df = pd.DataFrame([{
        "pair": "EURUSD", "rate": 1.08,
        "pct_change_1run": 5.0,
        "pct_change_60m":  5.0,
        "pct_change_24h":  5.0,
    }])
    result = apply_rules(df, cfg)
    assert not result["breach_1run"].iloc[0]
    assert not result["breach_60m"].iloc[0]
    assert not result["breach_24h"].iloc[0]
