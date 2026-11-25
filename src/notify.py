# src/notify.py
#
# Email (SMTP) notification channel.
#
# Configure via environment variables (set in your shell before running):
#
#   SMTP_HOST          e.g. smtp.gmail.com
#   SMTP_PORT          e.g. 587  (STARTTLS) or 465 (SSL)
#   SMTP_USER          your login / sender address
#   SMTP_PASSWORD      app password or SMTP password
#   EMAIL_RECIPIENT_1  first recipient address
#   EMAIL_RECIPIENT_2  second recipient address (optional)
#
# Gmail users: generate an App Password at
#   myaccount.google.com/apppasswords  (requires 2FA enabled)
from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd


def _fmt_pct(val) -> str:
    if pd.isna(val):
        return "    N/A"
    return f"{float(val):+.2f}%"


def _gold_commentary(pct_24h: float) -> str:
    """Return contextual commentary for gold's 24h % move."""
    if pct_24h > 3.0:
        return (
            "Significant upward move — gold surging, likely driven by risk-off "
            "sentiment, dollar weakness, or geopolitical stress."
        )
    if pct_24h > 1.5:
        return (
            "Notable daily gain — momentum building in gold, worth monitoring "
            "for continuation."
        )
    if pct_24h > 0.5:
        return "Modest positive move — gold drifting higher within normal daily range."
    if pct_24h >= -0.5:
        return "Gold relatively flat — no significant directional movement today."
    if pct_24h >= -1.5:
        return (
            "Modest decline — mild selling pressure, possibly dollar strength "
            "or risk-on rotation."
        )
    if pct_24h >= -3.0:
        return "Notable daily drop — gold pulling back, monitor for support levels."
    return "Sharp sell-off in gold — significant risk-on move or dollar surge likely in play."


def _breach_annotation(breach_type: str, value_pct: float) -> str:
    """Return a descriptive annotation string for a breach."""
    fmt = f"{value_pct:+.2f}%"
    if breach_type == "pct_change_24h":
        commentary = _gold_commentary(value_pct)
        return f"24h move of {fmt} exceeds threshold — {commentary}"
    if breach_type == "pct_change_60m":
        return f"60m move of {fmt} — unusual intraday velocity, potential news-driven spike."
    return f"Sharp move of {fmt} since last run — monitor for follow-through."


def _build_body(df_latest: pd.DataFrame, df_alerts: pd.DataFrame) -> tuple[str, str]:
    """Return (subject, plain-text body) for the update email."""
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Gold headline ──────────────────────────────────────────────────────────
    gold = df_latest[df_latest["pair"] == "XAUUSD"] if not df_latest.empty else pd.DataFrame()
    if not gold.empty:
        g = gold.iloc[0]
        gold_price = f"${g['rate']:,.2f}" if pd.notna(g.get("rate")) else "N/A"
        gold_24h_val = g.get("pct_change_24h")
        gold_24h_fmt = _fmt_pct(gold_24h_val)
        subject = f"FX Monitor — Gold {gold_price}  |  24h {gold_24h_fmt}"
    else:
        gold_price = "N/A"
        gold_24h_val = None
        subject = "FX Monitor — update"

    alert_count = len(df_alerts)
    if alert_count:
        subject += f"  |  {alert_count} alert{'s' if alert_count != 1 else ''}"

    # ── Breach annotation index: pair -> list of (breach_type, value_pct) ──────
    breach_index: dict[str, list[tuple[str, float]]] = {}
    if not df_alerts.empty:
        for _, row in df_alerts.iterrows():
            breach_index.setdefault(row["pair"], []).append(
                (row["breach_type"], float(row["value_pct"]))
            )

    # ── Body ───────────────────────────────────────────────────────────────────
    lines: list[str] = []
    lines.append(f"FX Monitor — {run_ts}")
    lines.append("=" * 60)

    # Gold section
    lines.append("")
    lines.append("GOLD (XAU/USD)")
    lines.append("-" * 40)
    if not gold.empty:
        g = gold.iloc[0]
        lines.append(f"  Price:          ${g['rate']:>10,.2f}")
        lines.append(f"  Since last run: {_fmt_pct(g.get('pct_change_1run')):>10}")
        lines.append(f"  60m change:     {_fmt_pct(g.get('pct_change_60m')):>10}")
        lines.append(f"  24h change:     {_fmt_pct(g.get('pct_change_24h')):>10}")
        lines.append("")
        if pd.notna(gold_24h_val):
            lines.append(f"  {_gold_commentary(float(gold_24h_val))}")
    else:
        lines.append("  No gold data available.")

    # All pairs table
    lines.append("")
    lines.append("ALL PAIRS")
    lines.append("-" * 60)
    lines.append(f"  {'Pair':<8}  {'Rate':>10}  {'1-run':>7}  {'60m':>7}  {'24h':>7}")
    lines.append(f"  {'-'*8}  {'-'*10}  {'-'*7}  {'-'*7}  {'-'*7}")

    if not df_latest.empty:
        for _, row in df_latest.sort_values("pair").iterrows():
            pair = row["pair"]
            lines.append(
                f"  {pair:<8}  {row['rate']:>10,.4f}"
                f"  {_fmt_pct(row.get('pct_change_1run')):>7}"
                f"  {_fmt_pct(row.get('pct_change_60m')):>7}"
                f"  {_fmt_pct(row.get('pct_change_24h')):>7}"
            )
            for breach_type, value_pct in breach_index.get(pair, []):
                lines.append(f"    ⚠  {_breach_annotation(breach_type, value_pct)}")

    # Alerts section
    lines.append("")
    if df_alerts.empty:
        lines.append("No thresholds breached this run.")
    else:
        lines.append(f"ALERTS ({alert_count})")
        lines.append("-" * 60)
        for _, row in df_alerts.iterrows():
            lines.append(f"  [{row['severity']}] {row['message']}")

    lines.append("")
    lines.append("─" * 60)
    lines.append("FX Monitor  •  python main.py --schedule 15:00,22:00")

    return subject, "\n".join(lines)


def send_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    email_from: str,
    recipients: list[str],
    df_latest: pd.DataFrame,
    df_alerts: pd.DataFrame,
) -> None:
    """
    Send the FX update email via SMTP.
    Always sends (including when there are no alerts) so scheduled runs
    at 15:00 and 22:00 always deliver a gold price update.
    Uses STARTTLS for port 587, SSL for port 465.
    """
    if not smtp_host or not smtp_user or not recipients:
        return

    recipients = [r for r in recipients if r and not r.startswith("${")]
    if not recipients:
        return

    port = int(smtp_port) if smtp_port else 587
    subject, body = _build_body(df_latest, df_alerts)

    msg = MIMEMultipart()
    msg["From"] = email_from or smtp_user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if port == 465:
        with smtplib.SMTP_SSL(smtp_host, port, timeout=15) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, recipients, msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, recipients, msg.as_string())
