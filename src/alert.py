# src/alert.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


ALERT_COLUMNS = [
    "alert_ts_utc",
    "pair",
    "severity",
    "breach_type",
    "value_pct",
    "threshold_pct",
    "rate",
    "message",
]


def _severity(breach_type: str) -> str:
    if breach_type == "pct_change_24h":
        return "HIGH"
    if breach_type == "pct_change_60m":
        return "MED"
    return "LOW"


def _recently_alerted(alerts_log_path: str, cooldown_minutes: int) -> set[tuple[str, str]]:
    """
    Returns the set of (pair, breach_type) combinations that already fired
    an alert within the cooldown window.  Used to suppress duplicate alerts.
    """
    if cooldown_minutes <= 0:
        return set()

    path = Path(alerts_log_path)
    if not path.exists():
        return set()

    try:
        df = pd.read_csv(path)
        if df.empty:
            return set()
        df["alert_ts_utc"] = pd.to_datetime(df["alert_ts_utc"], utc=True, errors="coerce")
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
        recent = df[df["alert_ts_utc"] >= cutoff]
        return set(zip(recent["pair"], recent["breach_type"]))
    except Exception:
        return set()


def build_alerts(
    df_ruled: pd.DataFrame,
    pairs_cfg: list[dict],
    alerts_log_path: str = "",
    cooldown_minutes: int = 0,
) -> pd.DataFrame:
    """
    Convert ruled latest rows into alert records.
    Creates one alert per breach type per pair.
    Suppresses re-alerts for the same (pair, breach_type) within cooldown_minutes.
    """
    thresholds = {p["name"]: p.get("thresholds", {}) for p in pairs_cfg}
    alert_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    suppressed = _recently_alerted(alerts_log_path, cooldown_minutes)

    alerts = []

    for _, row in df_ruled.iterrows():
        pair = row["pair"]
        th = thresholds.get(pair, {})

        breaches = [
            ("pct_change_1run", "breach_1run", th.get("pct_1run")),
            ("pct_change_60m",  "breach_60m",  th.get("pct_60m")),
            ("pct_change_24h",  "breach_24h",  th.get("pct_24h")),
        ]

        for metric_col, flag_col, threshold in breaches:
            flag = bool(row.get(flag_col, False))
            value = row.get(metric_col)

            if not (flag and pd.notna(value) and threshold is not None):
                continue

            if (pair, metric_col) in suppressed:
                continue

            severity = _severity(metric_col)
            direction = "up" if value >= 0 else "down"

            msg = (
                f"{pair} moved {direction} {abs(value):.2f}% "
                f"({metric_col}) vs threshold {threshold:.2f}%. "
                f"Latest rate={row.get('rate')}."
            )

            alerts.append(
                {
                    "alert_ts_utc": alert_ts,
                    "pair": pair,
                    "severity": severity,
                    "breach_type": metric_col,
                    "value_pct": float(value),
                    "threshold_pct": float(threshold),
                    "rate": row.get("rate"),
                    "message": msg,
                }
            )

    return pd.DataFrame(alerts, columns=ALERT_COLUMNS)


def append_alerts(df_alerts: pd.DataFrame, alerts_log_path: str) -> None:
    """Append alerts to alerts log CSV. Creates file if missing."""
    path = Path(alerts_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if df_alerts.empty:
        return

    if not path.exists():
        df_alerts.to_csv(path, index=False)
    else:
        df_alerts.to_csv(path, mode="a", header=False, index=False)
