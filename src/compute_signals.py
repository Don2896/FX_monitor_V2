# src/compute_signals.py
from __future__ import annotations

from datetime import timedelta
import pandas as pd


def _prep_history(df_history: pd.DataFrame) -> pd.DataFrame:
    df = df_history.copy()

    # Parse timestamps (UTC aware)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df["rate"] = pd.to_numeric(df["rate"], errors="coerce")

    # Drop bad rows
    df = df.dropna(subset=["timestamp_utc", "pair", "rate"])
    df = df.sort_values(["pair", "timestamp_utc"]).reset_index(drop=True)

    return df


def pct_change_last(df: pd.DataFrame) -> pd.Series:
    """% change vs previous observation within each pair."""
    prev = df.groupby("pair")["rate"].shift(1)
    return (df["rate"] / prev - 1.0) * 100.0


def pct_change_over_window(df: pd.DataFrame, window: timedelta) -> pd.Series:
    """
    % change vs the most recent observation at or before (timestamp - window), per pair.
    Uses merge_asof to align each row with an earlier row.
    """
    df_sorted = df.sort_values(["pair", "timestamp_utc"]).copy()

    # Build a "target time" column
    df_sorted["target_time"] = df_sorted["timestamp_utc"] - window

    # For merge_asof, we need per-pair merge; easiest is to do it pair-by-pair
    out = pd.Series(index=df_sorted.index, dtype="float64")

    for pair, g in df_sorted.groupby("pair", sort=False):
        g = g.sort_values("timestamp_utc").copy()

        left = g[["timestamp_utc", "target_time", "rate"]].copy()
        right = g[["timestamp_utc", "rate"]].rename(columns={"timestamp_utc": "ref_time", "rate": "ref_rate"})

        # merge_asof matches each row's target_time to the nearest ref_time <= target_time
        merged = pd.merge_asof(
            left.sort_values("target_time"),
            right.sort_values("ref_time"),
            left_on="target_time",
            right_on="ref_time",
            direction="backward",
            allow_exact_matches=True,
        )

        # Compute % change where we have a reference
        pct = (merged["rate"] / merged["ref_rate"] - 1.0) * 100.0
        out.loc[g.index] = pct.values

    return out


def compute_signals(df_history: pd.DataFrame) -> pd.DataFrame:
    """
    Returns df_history with additional signal columns:
    - pct_change_1run
    - pct_change_60m
    - pct_change_24h
    """
    df = _prep_history(df_history)

    if df.empty:
        return df

    df["pct_change_1run"] = pct_change_last(df)
    df["pct_change_60m"] = pct_change_over_window(df, timedelta(minutes=60))
    df["pct_change_24h"] = pct_change_over_window(df, timedelta(hours=24))

    return df
