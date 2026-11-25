# src/rules.py
from __future__ import annotations

import pandas as pd


def _safe_breach(value: float, threshold: float) -> bool:
    """
    Return True if abs(value) > threshold.
    Returns False (no breach) when value is NaN — this happens on first-run rows
    where there is no prior observation to compute a signal against.
    """
    if pd.isna(value):
        return False
    return abs(float(value)) > threshold


def apply_rules(df_latest: pd.DataFrame, pairs_cfg: list[dict]) -> pd.DataFrame:
    """
    Applies threshold rules from config onto latest signals.
    """
    df = df_latest.copy()

    thresholds = {
        p["name"]: p.get("thresholds", {})
        for p in pairs_cfg
    }

    breach_1run = []
    breach_60m = []
    breach_24h = []

    for _, row in df.iterrows():
        pair = row["pair"]
        th = thresholds.get(pair, {})

        breach_1run.append(_safe_breach(row.get("pct_change_1run"), th.get("pct_1run", float("inf"))))
        breach_60m.append(_safe_breach(row.get("pct_change_60m"), th.get("pct_60m", float("inf"))))
        breach_24h.append(_safe_breach(row.get("pct_change_24h"), th.get("pct_24h", float("inf"))))

    df["breach_1run"] = breach_1run
    df["breach_60m"] = breach_60m
    df["breach_24h"] = breach_24h

    return df
