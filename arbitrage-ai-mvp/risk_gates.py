"""Pure eligibility rules for the paper-trading simulator.

These helpers deliberately do not place orders or access the ledger.
"""
import math

MAX_VWAP_CHANGE_PCT = 0.30
MAX_MATCHED_VOLUME_CHANGE_PCT = 25.0
MAX_STABILITY_PROFIT_DROP_PCT = 30.0
PROFIT_DROP_WARNING_PCT = 3.0
PAPER_BLOCK_PROFIT_DROP_PCT = 5.0


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def profit_change_warning(value):
    change = _number(value)
    if change is None:
        return "در انتظار اسکن مقایسه‌ای"
    if change <= -PROFIT_DROP_WARNING_PCT:
        return "هشدار: افت سود ۳٪ یا بیشتر"
    return "بدون هشدار افت سود"


def is_paper_candidate(
    *,
    stable_scans,
    market_stable_now,
    validation_status,
    profit_toman,
    used_capital_toman,
    capital,
    profit_change_pct,
    stress_profit_slip_025_toman,
):
    """Return True only when every paper-simulation safety gate passes."""
    stable = _number(stable_scans)
    profit = _number(profit_toman)
    used_capital = _number(used_capital_toman)
    available_capital = _number(capital)
    change = _number(profit_change_pct)
    stress_profit = _number(stress_profit_slip_025_toman)

    return bool(
        stable is not None
        and stable >= 3
        and market_stable_now is True
        and validation_status == "قابل بررسی در شبیه‌سازی"
        and profit is not None
        and profit > 0
        and used_capital is not None
        and available_capital is not None
        and used_capital <= available_capital
        and (change is None or change > -PAPER_BLOCK_PROFIT_DROP_PCT)
        and stress_profit is not None
        and stress_profit > 0
    )
