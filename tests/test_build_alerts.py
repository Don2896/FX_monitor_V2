from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.alert import ALERT_COLUMNS, build_alerts, append_alerts


# ── Alert count and column schema ─────────────────────────────────────────────

def test_alert_count_matches_expected_breaches(ruled_df, pairs_cfg):
    # EURUSD breaches 3 windows; XAUUSD breaches 2 (1run + 24h) → 5 total
    alerts = build_alerts(ruled_df, pairs_cfg)
    assert len(alerts) == 5


def test_all_alert_columns_present(ruled_df, pairs_cfg):
    alerts = build_alerts(ruled_df, pairs_cfg)
    for col in ALERT_COLUMNS:
        assert col in alerts.columns


def test_no_alerts_when_no_breaches(pairs_cfg):
    df = pd.DataFrame([{
        "pair": "EURUSD", "rate": 1.08,
        "pct_change_1run": 0.01, "pct_change_60m": 0.01, "pct_change_24h": 0.01,
        "breach_1run": False, "breach_60m": False, "breach_24h": False,
    }])
    alerts = build_alerts(df, pairs_cfg)
    assert alerts.empty


def test_empty_input_returns_empty_with_columns(pairs_cfg):
    df = pd.DataFrame(columns=[
        "pair", "rate",
        "pct_change_1run", "pct_change_60m", "pct_change_24h",
        "breach_1run", "breach_60m", "breach_24h",
    ])
    alerts = build_alerts(df, pairs_cfg)
    assert alerts.empty
    for col in ALERT_COLUMNS:
        assert col in alerts.columns


# ── Per-pair alert breakdown ──────────────────────────────────────────────────

def test_eurusd_generates_three_alerts(ruled_df, pairs_cfg):
    alerts = build_alerts(ruled_df, pairs_cfg)
    eur_alerts = alerts[alerts["pair"] == "EURUSD"]
    assert len(eur_alerts) == 3
    assert set(eur_alerts["breach_type"]) == {
        "pct_change_1run", "pct_change_60m", "pct_change_24h"
    }


def test_xauusd_generates_two_alerts(ruled_df, pairs_cfg):
    alerts = build_alerts(ruled_df, pairs_cfg)
    xau_alerts = alerts[alerts["pair"] == "XAUUSD"]
    assert len(xau_alerts) == 2
    assert set(xau_alerts["breach_type"]) == {"pct_change_1run", "pct_change_24h"}


# ── Severity mapping ──────────────────────────────────────────────────────────

def test_severity_low_for_1run(ruled_df, pairs_cfg):
    alerts = build_alerts(ruled_df, pairs_cfg)
    row = alerts[alerts["breach_type"] == "pct_change_1run"].iloc[0]
    assert row["severity"] == "LOW"


def test_severity_med_for_60m(ruled_df, pairs_cfg):
    alerts = build_alerts(ruled_df, pairs_cfg)
    row = alerts[alerts["breach_type"] == "pct_change_60m"].iloc[0]
    assert row["severity"] == "MED"


def test_severity_high_for_24h(ruled_df, pairs_cfg):
    alerts = build_alerts(ruled_df, pairs_cfg)
    row = alerts[alerts["breach_type"] == "pct_change_24h"].iloc[0]
    assert row["severity"] == "HIGH"


# ── value_pct and threshold_pct stored correctly ──────────────────────────────

def test_value_pct_matches_signal(ruled_df, pairs_cfg, latest_signals_df):
    alerts = build_alerts(ruled_df, pairs_cfg)
    eur_1run_alert = alerts[
        (alerts["pair"] == "EURUSD") & (alerts["breach_type"] == "pct_change_1run")
    ].iloc[0]
    signal_val = latest_signals_df[latest_signals_df["pair"] == "EURUSD"].iloc[0]["pct_change_1run"]
    assert abs(eur_1run_alert["value_pct"] - signal_val) < 1e-6


def test_threshold_pct_matches_config(ruled_df, pairs_cfg):
    alerts = build_alerts(ruled_df, pairs_cfg)
    eur_1run_alert = alerts[
        (alerts["pair"] == "EURUSD") & (alerts["breach_type"] == "pct_change_1run")
    ].iloc[0]
    assert eur_1run_alert["threshold_pct"] == pytest.approx(0.10)


# ── Alert message content ─────────────────────────────────────────────────────

def test_message_contains_pair_name(ruled_df, pairs_cfg):
    alerts = build_alerts(ruled_df, pairs_cfg)
    for _, row in alerts.iterrows():
        assert row["pair"] in row["message"]


def test_message_contains_direction_up(ruled_df, pairs_cfg):
    alerts = build_alerts(ruled_df, pairs_cfg)
    # All fixture movements are positive
    for _, row in alerts.iterrows():
        assert "up" in row["message"]


def test_message_contains_rate(ruled_df, pairs_cfg, latest_signals_df):
    alerts = build_alerts(ruled_df, pairs_cfg)
    eur_rate = latest_signals_df[latest_signals_df["pair"] == "EURUSD"].iloc[0]["rate"]
    eur_alerts = alerts[alerts["pair"] == "EURUSD"]
    for _, row in eur_alerts.iterrows():
        assert str(eur_rate) in row["message"]


# ── Cooldown suppression ──────────────────────────────────────────────────────

def test_cooldown_suppresses_repeat_alerts(ruled_df, pairs_cfg, tmp_path):
    log_path = str(tmp_path / "alerts.csv")

    # First run: alerts fire normally
    first = build_alerts(ruled_df, pairs_cfg, alerts_log_path=log_path, cooldown_minutes=60)
    assert len(first) == 5
    append_alerts(first, alerts_log_path=log_path)

    # Second run with same breaches: all suppressed within cooldown window
    second = build_alerts(ruled_df, pairs_cfg, alerts_log_path=log_path, cooldown_minutes=60)
    assert second.empty


def test_cooldown_zero_never_suppresses(ruled_df, pairs_cfg, tmp_path):
    log_path = str(tmp_path / "alerts.csv")

    first = build_alerts(ruled_df, pairs_cfg, alerts_log_path=log_path, cooldown_minutes=0)
    append_alerts(first, alerts_log_path=log_path)

    second = build_alerts(ruled_df, pairs_cfg, alerts_log_path=log_path, cooldown_minutes=0)
    assert len(second) == 5


def test_cooldown_ignores_expired_alerts(ruled_df, pairs_cfg, tmp_path):
    log_path = str(tmp_path / "alerts.csv")

    # Write alerts with timestamps 2 hours ago (outside a 60-min cooldown)
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
    stale = build_alerts(ruled_df, pairs_cfg)
    stale["alert_ts_utc"] = stale_ts
    stale.to_csv(log_path, index=False)

    fresh = build_alerts(ruled_df, pairs_cfg, alerts_log_path=log_path, cooldown_minutes=60)
    assert len(fresh) == 5
