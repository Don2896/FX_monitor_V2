from __future__ import annotations

import argparse
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from datetime import timezone

import yaml

from src.fetch_rates import fetch_rates
from src.validate import validate_rates
from src.store import append_history
from src.compute_signals import compute_signals
from src.rules import apply_rules
from src.alert import build_alerts, append_alerts
from src.run_log import append_run_log
from src.notify import send_email


def _expand_env_vars(obj):
    """Recursively replace ${VAR_NAME} in config strings with os.environ values."""
    if isinstance(obj, str):
        return re.sub(r'\$\{(\w+)\}', lambda m: os.environ.get(m.group(1), m.group(0)), obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(i) for i in obj]
    return obj


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        cfg = yaml.safe_load(f)
    return _expand_env_vars(cfg)


def validate_config(cfg: dict) -> tuple[list[str], list[str]]:
    """
    Validate config structure.
    Returns (errors, warnings). Errors are fatal; warnings are printed but execution continues.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not cfg.get("source", {}).get("name"):
        errors.append("source.name is missing — cannot fetch rates")

    pairs = cfg.get("pairs", [])
    if not pairs:
        errors.append("No pairs defined under 'pairs:'")

    for p in pairs:
        name = p.get("name", "<unnamed>")
        if "base" not in p or "quote" not in p:
            errors.append(f"Pair '{name}' is missing base or quote")
        if "thresholds" not in p:
            warnings.append(f"Pair '{name}' has no thresholds — alerts will never fire for this pair")

    return errors, warnings


def ensure_dirs_exist() -> None:
    Path("data").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FX Monitor MVP")
    parser.add_argument("--config", type=str, default="config/pairs.yml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        metavar="MINUTES",
        help="Run every N minutes on repeat (0 = run once and exit)",
    )
    parser.add_argument(
        "--schedule",
        type=str,
        default="",
        metavar="HH:MM[,HH:MM...]",
        help=(
            "Run at specific local times daily, e.g. '15:00,22:00'. "
            "Times are in your system's local timezone. "
            "Use --interval for minute-based polling instead."
        ),
    )
    return parser.parse_args()


def _next_scheduled_run(times: list[str]) -> datetime:
    """Return the next datetime (local time) matching one of the HH:MM strings."""
    now = datetime.now()
    candidates: list[datetime] = []
    for t in times:
        h, m = map(int, t.strip().split(":"))
        candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        candidates.append(candidate)
    return min(candidates)


def _dispatch_email(cfg: dict, df_latest, df_alerts) -> None:
    """Send FX update email. Fires on every run including dry-run."""
    notify_cfg = cfg.get("notify", {})

    smtp_host   = notify_cfg.get("smtp_host", "")
    smtp_port   = notify_cfg.get("smtp_port", 587)
    smtp_user   = notify_cfg.get("smtp_user", "")
    smtp_pass   = notify_cfg.get("smtp_password", "")
    email_from  = notify_cfg.get("email_from", smtp_user)
    recipients  = notify_cfg.get("email_recipients", [])

    # Skip if config placeholders were not replaced by real env vars
    if not smtp_host or str(smtp_host).startswith("${"):
        return

    try:
        send_email(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_pass,
            email_from=email_from,
            recipients=recipients,
            df_latest=df_latest,
            df_alerts=df_alerts,
        )
        label = f"{len(df_alerts)} alert(s)" if not df_alerts.empty else "no alerts"
        print(f"  email: sent to {len(recipients)} recipient(s) ({label})")
    except Exception as exc:
        print(f"  WARNING: email notification failed: {exc}")


def run_once(args: argparse.Namespace, cfg: dict) -> int:
    """Execute one full monitoring pipeline. Returns 0 on success, 1 on failure."""
    start = time.time()

    runs_log_path    = cfg.get("run", {}).get("runs_log_path",    "logs/runs.csv")
    history_path     = cfg.get("run", {}).get("history_path",     "data/fx_history.csv")
    alerts_log_path  = cfg.get("run", {}).get("alerts_log_path",  "logs/alerts.csv")
    signals_out_path = cfg.get("run", {}).get("signals_out_path", "data/latest_signals.csv")

    retain_days      = cfg.get("history", {}).get("retain_days", 30)
    cooldown_minutes = cfg.get("alerts",  {}).get("cooldown_minutes", 0)

    pairs_cfg       = cfg.get("pairs", [])
    pair_names      = [p["name"] for p in pairs_cfg]
    pairs_requested = len(pair_names)

    status           = "FAIL"
    error_msg        = None
    pairs_returned   = 0
    alerts_triggered = 0
    history_rows     = 0

    try:
        run_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

        print("=" * 60)
        print("FX Monitor MVP")
        print("Run time (UTC):", run_ts)
        print("Pairs:", ", ".join(pair_names))
        print("Dry run:", args.dry_run)
        print("=" * 60)

        # 1. Fetch
        df_rates = fetch_rates(pairs_cfg=pairs_cfg, source_cfg=cfg.get("source", {}))

        # 2. Validate
        df_rates, validation_issues = validate_rates(df_rates)
        for issue in validation_issues:
            print(f"  VALIDATION WARNING: {issue}")

        pairs_returned = int(df_rates["pair"].nunique()) if not df_rates.empty else 0

        print("\nFetched rates:")
        if df_rates.empty:
            print("  No valid rates returned — aborting run")
            return 1
        print(df_rates[["timestamp_utc", "pair", "rate", "source"]].to_string(index=False))

        # 3. History
        df_history = append_history(df_rates, history_path=history_path, retain_days=retain_days)
        history_rows = len(df_history)

        dedupe_dropped = df_history.attrs.get("dedupe_dropped", 0)
        print(f"\nHistory updated: {history_path}")
        print(f"History rows: {history_rows} (duplicates dropped this run: {dedupe_dropped})")

        # 4. Signals
        df_with_signals = compute_signals(df_history)

        if df_with_signals.empty:
            print("\n  No history available to compute signals.")
        else:
            df_latest = (
                df_with_signals.sort_values(["pair", "timestamp_utc"])
                .groupby("pair", as_index=False)
                .tail(1)
                .reset_index(drop=True)
            )

            if not args.dry_run:
                df_latest.to_csv(signals_out_path, index=False)

            print("\nLatest signals:")
            print(
                df_latest[
                    ["pair", "rate", "pct_change_1run", "pct_change_60m", "pct_change_24h"]
                ].to_string(index=False)
            )
            if not args.dry_run:
                print(f"\nLatest signals written to {signals_out_path}")

            # 5. Rules
            df_ruled = apply_rules(df_latest, pairs_cfg=pairs_cfg)
            print("\nRule evaluation:")
            print(
                df_ruled[
                    ["pair", "pct_change_1run", "pct_change_60m", "pct_change_24h",
                     "breach_1run", "breach_60m", "breach_24h"]
                ].to_string(index=False)
            )

            # 6. Alerts
            df_alerts = build_alerts(
                df_ruled,
                pairs_cfg=pairs_cfg,
                alerts_log_path=alerts_log_path,
                cooldown_minutes=cooldown_minutes,
            )
            alerts_triggered = len(df_alerts)

            if df_alerts.empty:
                print("\nNo alerts triggered this run")
            else:
                print("\nALERTS TRIGGERED:")
                for msg in df_alerts["message"].tolist():
                    print(" ", msg)

                if not args.dry_run:
                    append_alerts(df_alerts, alerts_log_path=alerts_log_path)
                    print(f"\nAlerts appended to {alerts_log_path}")

            # Email fires on every run, including dry-run, to allow config testing
            print("\nSending email notification:")
            _dispatch_email(cfg, df_latest, df_alerts)

        status = "SUCCESS"
        return 0

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        print("\nRun failed:", error_msg)
        return 1

    finally:
        duration_ms = int((time.time() - start) * 1000)

        try:
            append_run_log(
                runs_log_path,
                status=status,
                pairs_requested=pairs_requested,
                pairs_returned=pairs_returned,
                alerts_triggered=alerts_triggered,
                history_rows=history_rows,
                duration_ms=duration_ms,
                error=error_msg,
            )
            print(f"\nRun logged to {runs_log_path} (status={status}, duration_ms={duration_ms})")
        except Exception as log_err:
            print("\nWARNING: Failed to write run log:", log_err)


def main() -> int:
    args = parse_args()
    ensure_dirs_exist()

    cfg = load_config(args.config)

    config_errors, config_warnings = validate_config(cfg)
    for w in config_warnings:
        print(f"CONFIG WARNING: {w}")
    if config_errors:
        for err in config_errors:
            print(f"CONFIG ERROR: {err}")
        return 1

    # -- Scheduling modes --

    if args.schedule:
        # Time-based: run at specific times each day (local system time)
        times = [t.strip() for t in args.schedule.split(",") if t.strip()]
        print(f"Scheduler: daily runs at {', '.join(times)} (local time). Ctrl+C to stop.\n")
        while True:
            run_once(args, cfg)
            next_run = _next_scheduled_run(times)
            wait_secs = (next_run - datetime.now()).total_seconds()
            print(f"\nNext run at {next_run.strftime('%H:%M')} local time "
                  f"(in {wait_secs / 60:.0f} minutes).\n")
            time.sleep(wait_secs)

    elif args.interval > 0:
        # Interval-based: run every N minutes
        print(f"Scheduler: running every {args.interval} minute(s). Ctrl+C to stop.\n")
        while True:
            run_once(args, cfg)
            print(f"\nSleeping {args.interval}m until next run…\n")
            time.sleep(args.interval * 60)

    else:
        # Single run
        return run_once(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
