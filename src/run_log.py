# src/run_log.py
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import pandas as pd


RUNLOG_COLUMNS = [
    "run_ts_utc",
    "status",
    "pairs_requested",
    "pairs_returned",
    "alerts_triggered",
    "history_rows",
    "duration_ms",
    "error",
]


def append_run_log(
    runs_log_path: str,
    *,
    status: str,
    pairs_requested: int,
    pairs_returned: int,
    alerts_triggered: int,
    history_rows: int,
    duration_ms: int,
    error: str | None = None,
) -> None:
    path = Path(runs_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    row = {
        "run_ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "pairs_requested": pairs_requested,
        "pairs_returned": pairs_returned,
        "alerts_triggered": alerts_triggered,
        "history_rows": history_rows,
        "duration_ms": duration_ms,
        "error": (error or "")[:300],  # keep it compact
    }

    df_row = pd.DataFrame([row], columns=RUNLOG_COLUMNS)

    if not path.exists():
        df_row.to_csv(path, index=False)
    else:
        df_row.to_csv(path, mode="a", header=False, index=False)
