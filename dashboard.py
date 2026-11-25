from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yaml

CONFIG_PATH = "config/pairs.yml"
HISTORY_PATH = "data/fx_history.csv"
SIGNALS_PATH = "data/latest_signals.csv"
ALERTS_PATH = "logs/alerts.csv"

SIGNAL_COLS = ["pct_change_1run", "pct_change_60m", "pct_change_24h"]
SIGNAL_THRESHOLD_KEYS = {
    "pct_change_1run": "pct_1run",
    "pct_change_60m": "pct_60m",
    "pct_change_24h": "pct_24h",
}
SEVERITY_COLOURS = {"HIGH": "#ff4444", "MED": "#ff9900", "LOW": "#ffcc00"}


# ── Data loaders ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@st.cache_data(ttl=60)
def load_history() -> pd.DataFrame:
    if not Path(HISTORY_PATH).exists():
        return pd.DataFrame(columns=["timestamp_utc", "pair", "rate", "source"])
    df = pd.read_csv(HISTORY_PATH)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    return df.dropna(subset=["timestamp_utc", "pair", "rate"])


@st.cache_data(ttl=60)
def load_signals() -> pd.DataFrame:
    if not Path(SIGNALS_PATH).exists():
        return pd.DataFrame()
    df = pd.read_csv(SIGNALS_PATH)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    return df


@st.cache_data(ttl=60)
def load_alerts() -> pd.DataFrame:
    if not Path(ALERTS_PATH).exists():
        return pd.DataFrame(columns=["alert_ts_utc", "pair", "severity", "breach_type",
                                     "value_pct", "threshold_pct", "rate", "message"])
    df = pd.read_csv(ALERTS_PATH)
    df["alert_ts_utc"] = pd.to_datetime(df["alert_ts_utc"], utc=True, errors="coerce")
    return df.sort_values("alert_ts_utc", ascending=False).reset_index(drop=True)


def thresholds_by_pair(cfg: dict) -> dict[str, dict]:
    return {p["name"]: p.get("thresholds", {}) for p in cfg.get("pairs", [])}


# ── Styling helpers ───────────────────────────────────────────────────────────

def _signal_cell_colour(value: float, threshold: float | None) -> str:
    if pd.isna(value) or threshold is None:
        return ""
    return "background-color: #ffcccc; color: #900" if abs(value) > threshold \
        else "background-color: #ccffcc; color: #060"


def style_signals_df(df: pd.DataFrame, thresholds: dict[str, dict]) -> pd.io.formats.style.Styler:
    def apply_colours(data: pd.DataFrame) -> pd.DataFrame:
        styles = pd.DataFrame("", index=data.index, columns=data.columns)
        for col in SIGNAL_COLS:
            if col not in data.columns:
                continue
            th_key = SIGNAL_THRESHOLD_KEYS[col]
            for idx in data.index:
                pair = data.at[idx, "pair"]
                th = thresholds.get(pair, {}).get(th_key)
                val = data.at[idx, col]
                styles.at[idx, col] = _signal_cell_colour(val, th)
        return styles

    return df.style.apply(apply_colours, axis=None).format(
        {c: "{:+.4f}%" for c in SIGNAL_COLS if c in df.columns},
        na_rep="—",
    )


def style_alerts_df(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    def row_colour(row: pd.Series) -> list[str]:
        colour = SEVERITY_COLOURS.get(row.get("severity", ""), "")
        bg = f"background-color: {colour}22" if colour else ""
        return [bg] * len(row)

    return df.style.apply(row_colour, axis=1).format(
        {"value_pct": "{:+.4f}%", "threshold_pct": "{:.4f}%"},
        na_rep="—",
    )


# ── Page layout ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="FX Monitor", layout="wide")
st.title("FX Monitor Dashboard")

# Auto-refresh every 60 seconds; returns the number of times the page has refreshed
st_autorefresh(interval=60_000, key="autorefresh")

cfg = load_config()
th = thresholds_by_pair(cfg)
all_pairs = [p["name"] for p in cfg.get("pairs", [])]

# Header row: last-updated timestamp + manual refresh button
_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
col_ts, col_btn = st.columns([4, 1])
with col_ts:
    st.caption(f"Last updated: {_ts}")
with col_btn:
    if st.button("Refresh now"):
        st.cache_data.clear()
        st.rerun()

st.info(
    "Data updates automatically when **main.py** is running. "
    "Use `python main.py --interval 10` to poll every 10 minutes, "
    "or `--schedule 15:00,22:00` to run at fixed times each day."
)

# ── Section 1: Latest Rates ───────────────────────────────────────────────────

st.header("1. Latest Rates")

df_signals = load_signals()

if df_signals.empty:
    st.info("No signals file found. Run `python main.py` to generate data.")
else:
    df_latest = (
        df_signals
        .sort_values(["pair", "timestamp_utc"])
        .groupby("pair", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    display_cols = [c for c in ["pair", "rate", "timestamp_utc", "source"] if c in df_latest.columns]
    st.dataframe(
        df_latest[display_cols].rename(columns={
            "pair": "Pair", "rate": "Rate", "timestamp_utc": "Timestamp (UTC)", "source": "Source"
        }),
        use_container_width=True,
        hide_index=True,
    )

# ── Section 2: Rate History Chart ─────────────────────────────────────────────

st.header("2. Rate History")

df_history = load_history()

if df_history.empty:
    st.info("No history file found. Run `python main.py` to generate data.")
else:
    selected_pairs = st.multiselect(
        "Select pair(s) to plot",
        options=sorted(df_history["pair"].unique()),
        default=sorted(df_history["pair"].unique()),
        key="history_pairs",
    )

    if selected_pairs:
        df_plot = (
            df_history[df_history["pair"].isin(selected_pairs)]
            .sort_values("timestamp_utc")
        )

        # Normalise each pair to % change from its own first observation so all
        # pairs share the same scale regardless of absolute price level.
        normed = []
        for pair, g in df_plot.groupby("pair"):
            g = g.sort_values("timestamp_utc").copy()
            first = g["rate"].iloc[0]
            g["pct_from_start"] = (g["rate"] / first - 1.0) * 100.0
            normed.append(g[["timestamp_utc", "pair", "pct_from_start"]])
        df_normed = pd.concat(normed)

        df_chart = (
            df_normed
            .pivot_table(index="timestamp_utc", columns="pair", values="pct_from_start", aggfunc="last")
            .sort_index()
        )

        st.line_chart(df_chart, use_container_width=True)
        st.caption("Y-axis: % change from each pair's first observation in the selected window.")
    else:
        st.info("Select at least one pair above.")

# ── Section 3: Signals ────────────────────────────────────────────────────────

st.header("3. Signals")

if df_signals.empty:
    st.info("No signals data available.")
else:
    df_sig_display = (
        df_signals
        .sort_values(["pair", "timestamp_utc"])
        .groupby("pair", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )

    cols_to_show = ["pair"] + [c for c in SIGNAL_COLS if c in df_sig_display.columns]
    df_sig_display = df_sig_display[cols_to_show]

    # Show thresholds as a reference table below
    styled = style_signals_df(df_sig_display, th)
    st.dataframe(styled, use_container_width=True, hide_index=True)

    with st.expander("Thresholds reference"):
        th_rows = [
            {
                "Pair": p["name"],
                "pct_1run threshold (%)": p.get("thresholds", {}).get("pct_1run", "—"),
                "pct_60m threshold (%)": p.get("thresholds", {}).get("pct_60m", "—"),
                "pct_24h threshold (%)": p.get("thresholds", {}).get("pct_24h", "—"),
            }
            for p in cfg.get("pairs", [])
        ]
        st.dataframe(pd.DataFrame(th_rows), use_container_width=True, hide_index=True)

# ── Section 4: Alert Log ──────────────────────────────────────────────────────

st.header("4. Alert Log")

df_alerts = load_alerts()

if df_alerts.empty:
    st.info("No alerts logged yet.")
else:
    col1, col2 = st.columns(2)
    with col1:
        severity_filter = st.multiselect(
            "Filter by severity",
            options=["HIGH", "MED", "LOW"],
            default=["HIGH", "MED", "LOW"],
            key="alert_severity",
        )
    with col2:
        pair_filter = st.multiselect(
            "Filter by pair",
            options=sorted(df_alerts["pair"].unique()),
            default=sorted(df_alerts["pair"].unique()),
            key="alert_pair",
        )

    df_filtered = df_alerts[
        df_alerts["severity"].isin(severity_filter) &
        df_alerts["pair"].isin(pair_filter)
    ]

    st.caption(f"Showing {len(df_filtered)} of {len(df_alerts)} alerts (most recent first)")
    st.dataframe(
        style_alerts_df(df_filtered.head(100)),
        use_container_width=True,
        hide_index=True,
    )
