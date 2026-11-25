# src/fetch_rates.py
#
# Supported sources:
#   frankfurter    — end-of-day ECB rates (https://api.frankfurter.app)
#                    Updates once per trading day ~16:00 CET.
#                    pct_change_1run / pct_change_60m will be 0 within the same day.
#
#   yahoo_finance  — real-time quotes via Yahoo Finance chart API (free, no key needed).
#                    Used for metals (XAU, XAG, XPT, XPD) and any Yahoo-listed symbol.
#                    Each pair must declare a `yahoo_symbol` field in pairs.yml.
#                    e.g. XAU/USD → yahoo_symbol: "GC=F"  (COMEX gold futures)
#
# Per-pair source selection: set source_override on any pair in pairs.yml
# to route that pair to a specific fetcher. Falls back to the global source.name.
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Any

import requests
import pandas as pd


_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = [2, 5]  # seconds between retries

_YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}

# Default Yahoo Finance symbols for common metal ISO codes
_DEFAULT_YAHOO_SYMBOLS: Dict[str, str] = {
    "XAU": "GC=F",   # COMEX gold futures (USD/troy oz)
    "XAG": "SI=F",   # COMEX silver futures
    "XPT": "PL=F",   # NYMEX platinum futures
    "XPD": "PA=F",   # NYMEX palladium futures
}


@dataclass(frozen=True)
class PairSpec:
    name: str
    base: str
    quote: str
    yahoo_symbol: str = ""   # required when source == yahoo_finance


def _get_with_retry(url: str, params: dict, timeout: int, headers: dict | None = None) -> requests.Response:
    """GET with up to _RETRY_ATTEMPTS attempts and exponential-ish backoff."""
    last_err: Exception | None = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            resp = requests.get(url, params=params, timeout=timeout, headers=headers or {})
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_err = exc
            if attempt < _RETRY_ATTEMPTS - 1:
                delay = _RETRY_BACKOFF[attempt]
                print(f"  Fetch attempt {attempt + 1} failed ({exc}). Retrying in {delay}s…")
                time.sleep(delay)
    raise last_err  # type: ignore[misc]


def fetch_rates_frankfurter(pair_specs: List[PairSpec], base_url: str) -> pd.DataFrame:
    """
    Fetch FX rates from Frankfurter.
    Groups requests by base currency to minimise API calls.
    """
    # Use space separator (not T) — pandas 2.x to_datetime(utc=True) rejects T format.
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00")

    base_to_quotes: Dict[str, List[str]] = {}
    for spec in pair_specs:
        base_to_quotes.setdefault(spec.base, []).append(spec.quote)

    rows = []
    for base, quotes in base_to_quotes.items():
        url = f"{base_url}/latest"
        params = {"from": base, "to": ",".join(sorted(set(quotes)))}

        resp = _get_with_retry(url, params=params, timeout=20)
        payload = resp.json()

        rates = payload.get("rates", {})
        for quote in quotes:
            rows.append(
                {
                    "timestamp_utc": run_ts,
                    "base": base,
                    "quote": quote,
                    "pair": f"{base}{quote}",
                    "rate": rates.get(quote),
                    "source": "frankfurter",
                }
            )

    df = pd.DataFrame(rows)
    if not df.empty:
        df["rate"] = pd.to_numeric(df["rate"], errors="coerce")
    return df


def fetch_rates_yahoo_finance(pair_specs: List[PairSpec]) -> pd.DataFrame:
    """
    Fetch real-time quotes from Yahoo Finance chart API (free, no API key).

    Each PairSpec must provide a yahoo_symbol (e.g. "GC=F" for gold futures).
    Falls back to a built-in default for common metal ISO codes (XAU, XAG, XPT, XPD).

    Note: Yahoo Finance does not require an API key but does require a User-Agent header.
    """
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00")
    rows = []

    for spec in pair_specs:
        symbol = spec.yahoo_symbol or _DEFAULT_YAHOO_SYMBOLS.get(spec.base.upper(), "")
        if not symbol:
            print(f"  WARNING: No yahoo_symbol for {spec.name} — skipping")
            continue

        url = f"{_YAHOO_BASE}/{symbol}"
        resp = _get_with_retry(url, params={}, timeout=20, headers=_YAHOO_HEADERS)
        payload = resp.json()

        try:
            price = payload["chart"]["result"][0]["meta"]["regularMarketPrice"]
        except (KeyError, IndexError, TypeError) as exc:
            print(f"  WARNING: Could not parse Yahoo Finance response for {spec.name}: {exc}")
            price = None

        rows.append(
            {
                "timestamp_utc": run_ts,
                "base": spec.base.upper(),
                "quote": spec.quote.upper(),
                "pair": spec.name,
                "rate": price,
                "source": "yahoo_finance",
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df["rate"] = pd.to_numeric(df["rate"], errors="coerce")
    return df


def fetch_rates(pairs_cfg: List[Dict[str, Any]], source_cfg: Dict[str, Any]) -> pd.DataFrame:
    """
    Public function used by main.py.

    Routes each pair to the correct fetcher based on:
    1. Per-pair `source_override` field (takes precedence)
    2. Global `source.name` in config
    """
    global_source = (source_cfg.get("name") or "").lower()
    frankfurter_url = source_cfg.get("base_url", "https://api.frankfurter.app").rstrip("/")

    frankfurter_specs: List[PairSpec] = []
    yahoo_specs: List[PairSpec] = []

    for p in pairs_cfg:
        src = p.get("source_override", global_source).lower()
        spec = PairSpec(
            name=p["name"],
            base=p["base"],
            quote=p["quote"],
            yahoo_symbol=p.get("yahoo_symbol", ""),
        )
        if src == "frankfurter":
            frankfurter_specs.append(spec)
        elif src == "yahoo_finance":
            yahoo_specs.append(spec)
        else:
            raise ValueError(f"Unknown source '{src}' for pair '{p['name']}'")

    dfs = []
    if frankfurter_specs:
        dfs.append(fetch_rates_frankfurter(frankfurter_specs, base_url=frankfurter_url))
    if yahoo_specs:
        dfs.append(fetch_rates_yahoo_finance(yahoo_specs))

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True)
