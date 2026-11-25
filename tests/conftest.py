from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest


def _ts(minutes_ago: int) -> str:
    t = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return t.strftime("%Y-%m-%d %H:%M:%S+00:00")


@pytest.fixture
def pairs_cfg() -> list[dict]:
    """
    Two-pair config used across signal, rules, and alert tests.

    Thresholds are chosen so that with the fx_history_df rates:
      EURUSD breaches all three windows (1run, 60m, 24h)
      XAUUSD breaches 1run and 24h only (pct_60m sits below 0.80 threshold)
    Total expected alerts: 5
    """
    return [
        {
            "name": "EURUSD",
            "base": "EUR",
            "quote": "USD",
            "thresholds": {"pct_1run": 0.10, "pct_60m": 0.15, "pct_24h": 0.40},
        },
        {
            "name": "XAUUSD",
            "base": "XAU",
            "quote": "USD",
            "thresholds": {"pct_1run": 0.40, "pct_60m": 0.80, "pct_24h": 1.50},
        },
    ]


@pytest.fixture
def fx_history_df() -> pd.DataFrame:
    """
    3-day history: 5 observations per pair, interleaved.

    EURUSD rates:  1.0800 → 1.0820 → 1.0850 → 1.0880 → 1.0900
    XAUUSD rates:  2800   → 2820   → 2850   → 2880   → 2900

    Observation ages: 4320 min (3 d), 2880 min (2 d), 1500 min (~25 h),
                      65 min, 5 min (latest).

    The 65-min-ago row is the exact 60-minute baseline for the latest row.
    The 1500-min-ago row is the closest prior to the 24-hour lookback
    from the 5-min-ago latest row (target = 1445 min ago).
    """
    rows = [
        # EURUSD
        {"timestamp_utc": _ts(4320), "pair": "EURUSD", "base": "EUR", "quote": "USD", "rate": 1.0800, "source": "test"},
        {"timestamp_utc": _ts(2880), "pair": "EURUSD", "base": "EUR", "quote": "USD", "rate": 1.0820, "source": "test"},
        {"timestamp_utc": _ts(1500), "pair": "EURUSD", "base": "EUR", "quote": "USD", "rate": 1.0850, "source": "test"},
        {"timestamp_utc": _ts(65),   "pair": "EURUSD", "base": "EUR", "quote": "USD", "rate": 1.0880, "source": "test"},
        {"timestamp_utc": _ts(5),    "pair": "EURUSD", "base": "EUR", "quote": "USD", "rate": 1.0900, "source": "test"},
        # XAUUSD
        {"timestamp_utc": _ts(4320), "pair": "XAUUSD", "base": "XAU", "quote": "USD", "rate": 2800.00, "source": "test"},
        {"timestamp_utc": _ts(2880), "pair": "XAUUSD", "base": "XAU", "quote": "USD", "rate": 2820.00, "source": "test"},
        {"timestamp_utc": _ts(1500), "pair": "XAUUSD", "base": "XAU", "quote": "USD", "rate": 2850.00, "source": "test"},
        {"timestamp_utc": _ts(65),   "pair": "XAUUSD", "base": "XAU", "quote": "USD", "rate": 2880.00, "source": "test"},
        {"timestamp_utc": _ts(5),    "pair": "XAUUSD", "base": "XAU", "quote": "USD", "rate": 2900.00, "source": "test"},
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def latest_signals_df(fx_history_df: pd.DataFrame) -> pd.DataFrame:
    """Latest signal row per pair, produced by compute_signals."""
    from src.compute_signals import compute_signals

    df_with_signals = compute_signals(fx_history_df)
    return (
        df_with_signals
        .sort_values(["pair", "timestamp_utc"])
        .groupby("pair", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )


@pytest.fixture
def ruled_df(latest_signals_df: pd.DataFrame, pairs_cfg: list[dict]) -> pd.DataFrame:
    """latest_signals_df after apply_rules."""
    from src.rules import apply_rules

    return apply_rules(latest_signals_df, pairs_cfg)
