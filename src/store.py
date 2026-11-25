# src/store.py
from __future__ import annotations

from pathlib import Path

import pandas as pd


HISTORY_COLUMNS = ["timestamp_utc", "pair", "base", "quote", "rate", "source"]


def init_history(history_path: str) -> None:
    """Create an empty history CSV with the correct schema if it doesn't exist."""
    path = Path(history_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        df_empty = pd.DataFrame(columns=HISTORY_COLUMNS)
        df_empty.to_csv(path, index=False)


def _prune_history(df: pd.DataFrame, retain_days: int) -> pd.DataFrame:
    """Drop rows older than retain_days. Pass retain_days=0 to skip pruning."""
    if retain_days <= 0:
        return df
    df = df.copy()
    # Normalise separator: pandas 2.x to_datetime(utc=True) rejects ISO T-format strings.
    df["timestamp_utc"] = pd.to_datetime(
        df["timestamp_utc"].astype(str).str.replace("T", " ", regex=False),
        utc=True,
        errors="coerce",
    )
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=retain_days)
    return df[df["timestamp_utc"] >= cutoff].reset_index(drop=True)


def append_history(
    df_rates: pd.DataFrame,
    history_path: str,
    retain_days: int = 30,
) -> pd.DataFrame:
    """
    Append rates to history, enforce schema, drop duplicates on (timestamp_utc, pair),
    and prune rows older than retain_days.

    Returns the updated full history DataFrame.
    """
    init_history(history_path)

    path = Path(history_path)

    missing = [c for c in HISTORY_COLUMNS if c not in df_rates.columns]
    if missing:
        raise ValueError(f"df_rates missing required columns: {missing}")

    df_hist = pd.read_csv(path)

    df_in = df_rates[HISTORY_COLUMNS].copy()

    df_all = pd.concat([df_hist, df_in], ignore_index=True)

    # Normalize types
    df_all["timestamp_utc"] = df_all["timestamp_utc"].astype(str)
    df_all["pair"] = df_all["pair"].astype(str)
    df_all["base"] = df_all["base"].astype(str)
    df_all["quote"] = df_all["quote"].astype(str)
    df_all["source"] = df_all["source"].astype(str)
    df_all["rate"] = pd.to_numeric(df_all["rate"], errors="coerce")

    before = len(df_all)
    df_all = df_all.drop_duplicates(subset=["timestamp_utc", "pair"], keep="last")
    after = len(df_all)

    df_all = df_all.sort_values(["pair", "timestamp_utc"]).reset_index(drop=True)

    # Prune old rows
    df_all = _prune_history(df_all, retain_days=retain_days)

    # Normalise timestamp back to string after potential datetime conversion in prune
    df_all["timestamp_utc"] = df_all["timestamp_utc"].astype(str)

    df_all.to_csv(path, index=False)

    df_all.attrs["dedupe_dropped"] = before - after

    return df_all
