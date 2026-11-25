from __future__ import annotations

import pandas as pd
import pytest

from src.validate import validate_rates, RATE_MIN, RATE_MAX


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_df(*rates, pair="EURUSD") -> pd.DataFrame:
    return pd.DataFrame(
        [{"pair": pair, "rate": r} for r in rates]
    )


# ── Normal operation ──────────────────────────────────────────────────────────

def test_valid_rows_pass_through():
    df = _make_df(1.08, 1.09, 1.10)
    clean, issues = validate_rates(df)
    assert len(clean) == 3
    assert issues == []


def test_clean_df_index_is_reset():
    df = _make_df(1.08, 1.09, 1.10)
    clean, _ = validate_rates(df)
    assert list(clean.index) == [0, 1, 2]


def test_multi_pair_all_valid():
    df = pd.DataFrame([
        {"pair": "EURUSD", "rate": 1.08},
        {"pair": "XAUUSD", "rate": 2900.0},
    ])
    clean, issues = validate_rates(df)
    assert len(clean) == 2
    assert issues == []


# ── Null rate ─────────────────────────────────────────────────────────────────

def test_null_rate_row_is_dropped():
    df = pd.DataFrame([
        {"pair": "EURUSD", "rate": 1.08},
        {"pair": "EURUSD", "rate": None},
    ])
    clean, issues = validate_rates(df)
    assert len(clean) == 1
    assert clean.iloc[0]["rate"] == 1.08


def test_null_rate_produces_issue_message():
    df = _make_df(None, pair="XAUUSD")
    _, issues = validate_rates(df)
    assert len(issues) == 1
    assert "XAUUSD" in issues[0]
    assert "null" in issues[0].lower()


def test_all_null_rates_returns_empty():
    df = pd.DataFrame([
        {"pair": "EURUSD", "rate": None},
        {"pair": "XAUUSD", "rate": None},
    ])
    clean, issues = validate_rates(df)
    assert clean.empty
    assert len(issues) == 2


# ── Non-positive rate ─────────────────────────────────────────────────────────

def test_zero_rate_row_is_dropped():
    df = pd.DataFrame([
        {"pair": "EURUSD", "rate": 0.0},
        {"pair": "EURUSD", "rate": 1.08},
    ])
    clean, issues = validate_rates(df)
    assert len(clean) == 1
    assert 1.08 in clean["rate"].values


def test_negative_rate_row_is_dropped():
    # validate_rates checks nonpos AND implausible independently, so a negative
    # value fires both checks and produces 2 issue strings.
    df = _make_df(-1.0, pair="EURUSD")
    clean, issues = validate_rates(df)
    assert clean.empty
    assert any("<= 0" in msg for msg in issues)


def test_nonpos_issue_contains_pair_and_value():
    df = _make_df(-5.0, pair="XAUUSD")
    _, issues = validate_rates(df)
    assert "XAUUSD" in issues[0]
    assert "-5.0" in issues[0]


# ── Implausible range ─────────────────────────────────────────────────────────

def test_rate_below_min_is_dropped():
    df = _make_df(RATE_MIN / 2, pair="EURUSD")
    clean, issues = validate_rates(df)
    assert clean.empty
    assert len(issues) == 1
    assert "plausible range" in issues[0].lower()


def test_rate_above_max_is_dropped():
    df = _make_df(RATE_MAX + 1.0, pair="EURUSD")
    clean, issues = validate_rates(df)
    assert clean.empty
    assert len(issues) == 1
    assert "plausible range" in issues[0].lower()


def test_rate_at_exact_min_is_kept():
    df = _make_df(RATE_MIN, pair="EURUSD")
    clean, issues = validate_rates(df)
    assert len(clean) == 1
    assert issues == []


def test_rate_at_exact_max_is_kept():
    df = _make_df(RATE_MAX, pair="EURUSD")
    clean, issues = validate_rates(df)
    assert len(clean) == 1
    assert issues == []


def test_implausible_issue_contains_pair_and_rate():
    extreme = RATE_MAX * 2
    df = _make_df(extreme, pair="XAUUSD")
    _, issues = validate_rates(df)
    assert "XAUUSD" in issues[0]
    assert str(extreme) in issues[0]


# ── Mixed valid / invalid rows ────────────────────────────────────────────────

def test_only_valid_rows_returned_in_mixed_df():
    # null → 1 issue; -0.5 → 2 issues (nonpos + implausible); RATE_MAX*2 → 1 issue → 4 total
    df = pd.DataFrame([
        {"pair": "EURUSD", "rate": 1.08},        # valid
        {"pair": "EURUSD", "rate": None},         # null (1 issue)
        {"pair": "EURUSD", "rate": -0.5},         # non-positive + implausible (2 issues)
        {"pair": "EURUSD", "rate": RATE_MAX * 2}, # implausible only (1 issue)
        {"pair": "EURUSD", "rate": 1.09},         # valid
    ])
    clean, issues = validate_rates(df)
    assert list(clean["rate"]) == [1.08, 1.09]
    assert len(issues) == 4


def test_issue_count_for_mixed_bad_rows():
    # null → 1 issue; -1.0 → 2 issues (nonpos + implausible); valid → 0 → 3 total
    df = pd.DataFrame([
        {"pair": "A", "rate": None},
        {"pair": "B", "rate": -1.0},
        {"pair": "C", "rate": 1.0},  # valid
    ])
    _, issues = validate_rates(df)
    assert len(issues) == 3


# ── Empty and single-row edge cases ──────────────────────────────────────────

def test_empty_dataframe_returns_empty_with_no_issues():
    df = pd.DataFrame(columns=["pair", "rate"])
    clean, issues = validate_rates(df)
    assert clean.empty
    assert issues == []


def test_single_valid_row():
    df = _make_df(1.08)
    clean, issues = validate_rates(df)
    assert len(clean) == 1
    assert issues == []


def test_single_null_row():
    df = _make_df(None)
    clean, issues = validate_rates(df)
    assert clean.empty
    assert len(issues) == 1


def test_single_negative_row():
    # -100.0 triggers both nonpos and implausible checks → 2 issues, row dropped
    df = _make_df(-100.0)
    clean, issues = validate_rates(df)
    assert clean.empty
    assert len(issues) == 2
