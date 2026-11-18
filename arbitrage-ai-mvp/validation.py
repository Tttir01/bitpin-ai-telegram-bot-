"""Delayed re-pricing of recorded opportunities using fresh public order books."""
import math
from datetime import datetime, timezone

from scanner import buy_from_asks, sell_into_bids


HORIZONS_DEFAULT = (60, 300, 900)
GRACE_SECONDS = 600


def _num(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def to_timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def build_entry(item, config):
    """Freeze the route and all cost assumptions used at the initial observation."""
    buy_exchange = item.get("buy_exchange")
    sell_exchange = item.get("sell_exchange")
    fee_buy_default = config.get(
        "fee_local" if buy_exchange == "Wallex" else "fee_global", 0.0025
    )
    fee_sell_default = config.get(
        "fee_local" if sell_exchange == "Wallex" else "fee_global", 0.0025
    )
    fixed_fee = item.get("fixed_fee_coin")
    transfer_pct = item.get("transfer_pct_applied")
    if transfer_pct is None:
        transfer_pct = _num(config.get("transfer_cost_pct", 0.30)) / 100

    return {
        "symbol": item["symbol"],
        "base": str(item["symbol"]).split("/")[0],
        "buy_exchange": buy_exchange,
        "sell_exchange": sell_exchange,
        "capital_toman": _num(config.get("capital", config.get("capital_toman", 2_000_000))),
        "min_order_toman": _num(config.get("min_order_toman", 0)),
        "buy_fee": _num(fee_buy_default),
        "sell_fee": _num(fee_sell_default),
        "slippage": _num(config.get("slippage_pct", 0.20)) / 100,
        "transfer_pct": _num(transfer_pct),
        "fixed_fee_coin": _num(fixed_fee) if fixed_fee is not None else None,
        "initial_profit_toman": _num(item.get("profit_toman")),
        "initial_used_capital_toman": _num(item.get("used_capital_toman")),
        "initial_base_quantity": _num(item.get("base_quantity")),
    }


def reprice_entry(entry, wallex_books, nobitex_books):
    """Recalculate the exact recorded route on the supplied fresh snapshot."""
    buy_books = wallex_books if entry["buy_exchange"] == "Wallex" else nobitex_books
    sell_books = wallex_books if entry["sell_exchange"] == "Wallex" else nobitex_books
    symbol = entry["symbol"]
    buy_book = buy_books.get(symbol)
    sell_book = sell_books.get(symbol)
    if not buy_book or not sell_book:
        return {"status": "route_missing"}

    asks = buy_book.get("asks") or []
    bids = sell_book.get("bids") or []
    if not asks or not bids:
        return {"status": "empty_order_book"}

    buy_fee = _num(entry.get("buy_fee"))
    sell_fee = _num(entry.get("sell_fee"))
    slippage = max(0.0, _num(entry.get("slippage")))
    transfer_pct = max(0.0, _num(entry.get("transfer_pct")))
    fixed_fee = entry.get("fixed_fee_coin")
    fixed_fee = _num(fixed_fee) if fixed_fee is not None else None
    capital = _num(entry.get("capital_toman"))

    # Re-price the originally recorded quantity, not a smaller newly optimized trade.
    target_buy_qty = _num(entry.get("initial_base_quantity"))
    if target_buy_qty <= 0:
        return {"status": "invalid_recorded_quantity"}
    buy_budget = capital / (1.0 + transfer_pct)
    bought_qty, raw_buy_cost = buy_from_asks(
        asks, buy_budget, target_buy_qty, buy_fee, slippage
    )
    if bought_qty + max(1e-12, target_buy_qty * 1e-8) < target_buy_qty:
        return {"status": "insufficient_buy_depth"}
    if bought_qty <= 0:
        return {"status": "insufficient_buy_depth"}

    sell_qty = bought_qty - fixed_fee if fixed_fee is not None else bought_qty
    if sell_qty <= 0:
        return {"status": "withdrawal_fee_exceeds_quantity"}

    sold_qty, raw_sell_value, net_sell_value, levels_used = sell_into_bids(
        bids, sell_qty, sell_fee, slippage
    )
    if sold_qty + max(1e-12, sell_qty * 1e-8) < sell_qty:
        return {"status": "insufficient_sell_depth"}

    buy_debit = raw_buy_cost * (1.0 + buy_fee) * (1.0 + slippage)
    transfer_cost = raw_buy_cost * transfer_pct
    profit = net_sell_value - buy_debit - transfer_cost
    used_capital = buy_debit + transfer_cost
    if used_capital < _num(entry.get("min_order_toman")):
        return {"status": "below_minimum_order"}

    return {
        "status": "ok",
        "profit_toman": round(profit),
        "used_capital_toman": round(used_capital),
        "net_spread_pct": round(profit / used_capital * 100, 6) if used_capital else -100,
        "base_quantity": bought_qty,
        "sold_quantity": sold_qty,
        "buy_vwap": raw_buy_cost / bought_qty,
        "sell_vwap": raw_sell_value / sold_qty,
        "sell_levels_used": levels_used,
        "real_order_placed": False,
    }


def process_pending(rows, wallex_books, nobitex_books, now, horizons=HORIZONS_DEFAULT):
    """Return (row_id, merged_results, done) updates for due validation horizons."""
    updates = []
    horizons = tuple(sorted(set(int(h) for h in horizons)))
    for row in rows or []:
        if row.get("done"):
            continue
        created = to_timestamp(row.get("created_at"))
        if created is None:
            updates.append((row.get("id"), row.get("results") or {}, True))
            continue
        entry = row.get("entry") or {}
        results = dict(row.get("results") or {})
        changed = False

        for horizon in horizons:
            key = str(horizon)
            if key in results:
                continue
            target = created + horizon
            if now < target:
                continue
            elapsed_late = now - target
            if elapsed_late > GRACE_SECONDS:
                result = {"status": "missed", "target_at": target, "observed_at": now}
            else:
                result = reprice_entry(entry, wallex_books, nobitex_books)
                result["target_at"] = target
                result["observed_at"] = now
                result["delay_seconds"] = round(elapsed_late, 2)
            results[key] = result
            changed = True

        done = all(str(h) in results for h in horizons)
        if changed or done:
            updates.append((row.get("id"), results, done))
    return updates
