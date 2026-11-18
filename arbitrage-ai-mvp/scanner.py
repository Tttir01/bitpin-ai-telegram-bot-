"""Depth-aware public order-book scanner for paper-only arbitrage."""
import math
import time
from concurrent.futures import ThreadPoolExecutor

import requests

WALLEX = "https://api.wallex.ir"
NOBITEX = "https://apiv2.nobitex.ir"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ArbitrageAI/0.10)", "Accept": "application/json"}
MAX_BOOK_AGE_SECONDS = 90
MAX_SNAPSHOT_SKEW_SECONDS = 15
MAX_SANE_SPREAD_PCT = 15.0


def get_json(url, retries=2):
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, timeout=(5, 15), headers=HEADERS)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(attempt + 1)
                continue
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            last_error = error
            status = getattr(getattr(error, "response", None), "status_code", None)
            if status not in (None, 429, 500, 502, 503, 504) or attempt >= retries:
                raise
            time.sleep(attempt + 1)
    raise last_error


def normalize_symbol(raw, quotes):
    symbol = str(raw or "").upper().replace("_", "/").replace("-", "/")
    if "/" not in symbol:
        for quote in sorted(quotes, key=len, reverse=True):
            if symbol.endswith(quote) and len(symbol) > len(quote):
                return symbol[:-len(quote)] + "/" + quote
    return symbol


def positive_float(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def parse_levels(levels, side):
    parsed = []
    for level in levels or []:
        try:
            if isinstance(level, dict):
                price = positive_float(level.get("price"))
                quantity = positive_float(level.get("quantity", level.get("qty")))
            else:
                price, quantity = positive_float(level[0]), positive_float(level[1])
            if price is not None and quantity is not None:
                parsed.append((price, quantity))
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    return sorted(parsed, key=lambda x: x[0], reverse=(side == "bid"))


def wallex_books():
    started = time.time()
    payload = get_json(f"{WALLEX}/v2/depth/all")
    received = time.time()
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise RuntimeError("پاسخ دفتر سفارش عمومی والکس معتبر نیست.")
    result = payload.get("result") or payload.get("data") or {}
    if isinstance(result, dict) and isinstance(result.get("symbols"), dict):
        result = result["symbols"]
    books = {}
    for raw_symbol, book in result.items():
        if not isinstance(book, dict):
            continue
        symbol = normalize_symbol(raw_symbol, ("USDT", "USDC", "TMN", "IRT", "BTC", "ETH")).replace("/TMN", "/IRT")
        asks = parse_levels(book.get("ask") or book.get("asks"), "ask")
        bids = parse_levels(book.get("bid") or book.get("bids"), "bid")
        if asks and bids:
            books[symbol] = {
                "asks": asks, "bids": bids, "updated_at": None,
                "received_at": received, "latency_ms": round((received - started) * 1000),
                "source": "Wallex",
            }
    if not books:
        raise RuntimeError("از دفتر سفارش عمومی والکس داده قابل استفاده دریافت نشد.")
    return books


def nobitex_books():
    started = time.time()
    payload = get_json(f"{NOBITEX}/v3/orderbook/all")
    received = time.time()
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise RuntimeError("پاسخ دفتر سفارش عمومی نوبیتکس معتبر نیست.")
    books = {}
    for raw_symbol, book in payload.items():
        if raw_symbol in ("status", "message") or not isinstance(book, dict):
            continue
        symbol = normalize_symbol(raw_symbol, ("USDT", "USDC", "IRT", "RLS", "BTC", "ETH"))
        asks = parse_levels(book.get("asks"), "ask")
        bids = parse_levels(book.get("bids"), "bid")
        if not asks or not bids:
            continue
        divisor = 10.0 if symbol.endswith("/IRT") else 1.0
        asks = [(price / divisor, qty) for price, qty in asks]
        bids = [(price / divisor, qty) for price, qty in bids]
        updated = book.get("lastUpdate")
        try:
            updated = float(updated) / 1000 if updated else None
        except (TypeError, ValueError, OverflowError):
            updated = None
        books[symbol] = {
            "asks": asks, "bids": bids, "updated_at": updated,
            "received_at": received, "latency_ms": round((received - started) * 1000),
            "source": "Nobitex",
        }
    if not books:
        raise RuntimeError("از دفتر سفارش عمومی نوبیتکس داده قابل استفاده دریافت نشد.")
    return books


def fetch_both_books():
    """Fetch both exchanges concurrently; returns (wallex, nobitex, errors)."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(wallex_books), pool.submit(nobitex_books))
        results, errors = [], []
        for name, future in zip(("Wallex", "Nobitex"), futures):
            try:
                results.append(future.result())
            except Exception as error:
                results.append({})
                errors.append(f"{name} API: {type(error).__name__}: {error}")
    return results[0], results[1], errors


def buy_from_asks(asks, quote_budget, max_base_qty, fee, slippage):
    remaining_budget, remaining_qty = quote_budget, max_base_qty
    base_qty = raw_cost = 0.0
    for price, available in asks:
        if remaining_budget <= 0 or remaining_qty <= 0:
            break
        unit_cost = price * (1 + fee) * (1 + slippage)
        qty = min(available, remaining_qty, remaining_budget / unit_cost)
        if qty <= 0:
            continue
        raw_cost += price * qty
        base_qty += qty
        remaining_qty -= qty
        remaining_budget -= qty * unit_cost
    return base_qty, raw_cost


def sell_into_bids(bids, base_qty, fee, slippage):
    remaining, raw_proceeds, sold, levels_used = base_qty, 0.0, 0.0, 0
    for price, available in bids:
        if remaining <= 0:
            break
        qty = min(available, remaining)
        if qty > 0:
            levels_used += 1
            raw_proceeds += price * qty
            sold += qty
            remaining -= qty
    net_proceeds = raw_proceeds * (1 - fee) * (1 - slippage)
    return sold, raw_proceeds, net_proceeds, levels_used


def levels_required(levels, quantity):
    remaining, used = quantity, 0
    for _, available in levels:
        if remaining <= 1e-12:
            break
        take = min(available, remaining)
        if take > 0:
            used += 1
            remaining -= take
    return used


def fixed_withdrawal_fee(fees, exchange, base):
    for key in (f"{exchange}:{base}", base):
        value = fees.get(key)
        try:
            number = float(value)
            if math.isfinite(number) and number >= 0:
                return number
        except (TypeError, ValueError, OverflowError):
            pass
    return None


def scan_markets(
    fee_local=0.0025, fee_global=0.0025, slippage_pct=0.20,
    transfer_cost_pct=0.30, capital_toman=2_000_000,
    max_book_age_seconds=MAX_BOOK_AGE_SECONDS, withdrawal_fees=None,
    min_order_toman=0, books=None, now=None,
):
    """Paper-only depth simulation. No private keys, balances, transfers or orders."""
    opportunities, diagnostics = [], {}
    if books is None:
        wallex, nobitex, errors = fetch_both_books()
    else:
        wallex, nobitex, errors = books
    errors = list(errors or [])
    now = time.time() if now is None else float(now)
    fees = {}
    for key, value in (withdrawal_fees or {}).items():
        try:
            fees[str(key)] = float(value)
        except (TypeError, ValueError, OverflowError):
            continue

    diagnostics.update({
        "wallex_books": len(wallex), "nobitex_books": len(nobitex),
        "common_symbols": len(set(wallex) & set(nobitex)), "suspicious_skipped": 0,
    })
    slippage = max(0.0, float(slippage_pct)) / 100
    transfer = max(0.0, float(transfer_cost_pct)) / 100
    fee_wallex, fee_nobitex = max(0.0, float(fee_local)), max(0.0, float(fee_global))

    for symbol in sorted(set(wallex) & set(nobitex)):
        if not symbol.endswith("/IRT"):
            continue
        base = symbol.split("/")[0]
        for buy_name, buy_book, buy_fee in (
            ("Wallex", wallex[symbol], fee_wallex),
            ("Nobitex", nobitex[symbol], fee_nobitex),
        ):
            for sell_name, sell_book, sell_fee in (
                ("Wallex", wallex[symbol], fee_wallex),
                ("Nobitex", nobitex[symbol], fee_nobitex),
            ):
                if buy_name == sell_name:
                    continue
                buy_age = now - buy_book["updated_at"] if buy_book.get("updated_at") else None
                sell_age = now - sell_book["updated_at"] if sell_book.get("updated_at") else None
                if any(age is not None and (age < -5 or age > max_book_age_seconds) for age in (buy_age, sell_age)):
                    continue
                best_ask, best_bid = buy_book["asks"][0][0], sell_book["bids"][0][0]
                spread_pct = (best_bid / best_ask - 1) * 100
                if spread_pct > MAX_SANE_SPREAD_PCT:
                    diagnostics["suspicious_skipped"] += 1
                    continue

                sell_depth = sum(qty for _, qty in sell_book["bids"])
                if sell_depth <= 0:
                    continue
                fixed_fee = fixed_withdrawal_fee(fees, buy_name, base)
                transfer_pct = 0.0 if fixed_fee is not None else transfer
                buy_budget = float(capital_toman) / (1 + transfer_pct)
                bought_qty, raw_buy_cost = buy_from_asks(
                    buy_book["asks"], buy_budget, sell_depth + (fixed_fee or 0.0),
                    buy_fee, slippage,
                )
                if bought_qty <= 0 or raw_buy_cost <= 0:
                    continue
                sell_qty = bought_qty - fixed_fee if fixed_fee is not None else bought_qty
                if sell_qty <= 0:
                    continue
                sold_qty, raw_sell_value, net_sell_value, sell_levels_used = sell_into_bids(
                    sell_book["bids"], sell_qty, sell_fee, slippage
                )
                if sold_qty + max(1e-12, sell_qty * 1e-8) < sell_qty or sold_qty <= 0:
                    continue

                buy_vwap, sell_vwap = raw_buy_cost / bought_qty, raw_sell_value / sold_qty
                buy_debit = raw_buy_cost * (1 + buy_fee) * (1 + slippage)
                pct_transfer_cost = raw_buy_cost * transfer_pct
                net_profit = net_sell_value - buy_debit - pct_transfer_cost
                used_capital = buy_debit + pct_transfer_cost
                if used_capital < float(min_order_toman):
                    continue
                net_pct = net_profit / used_capital * 100 if used_capital else -100

                stress = {}
                for extra in (0.10, 0.25, 0.50):
                    stressed = slippage + extra / 100
                    stress[extra] = (
                        raw_sell_value * (1 - sell_fee) * (1 - stressed)
                        - raw_buy_cost * (1 + buy_fee) * (1 + stressed)
                        - pct_transfer_cost
                    )
                stress_denominator = raw_buy_cost * (1 + buy_fee) + raw_sell_value * (1 - sell_fee)
                max_extra = max(0.0, net_profit / stress_denominator * 100) if stress_denominator > 0 else 0.0

                buy_fee_cost = raw_buy_cost * buy_fee
                buy_slippage_cost = raw_buy_cost * (1 + buy_fee) * slippage
                sell_fee_cost = raw_sell_value * sell_fee
                sell_slippage_cost = raw_sell_value * (1 - sell_fee) * slippage
                transfer_cost = fixed_fee * buy_vwap if fixed_fee is not None else pct_transfer_cost

                buy_received_age = max(0.0, now - buy_book["received_at"])
                sell_received_age = max(0.0, now - sell_book["received_at"])
                effective_buy_age = buy_age if buy_age is not None else buy_received_age
                effective_sell_age = sell_age if sell_age is not None else sell_received_age
                skew = abs(buy_book["received_at"] - sell_book["received_at"])
                fresh = effective_buy_age <= max_book_age_seconds and effective_sell_age <= max_book_age_seconds
                snapshot_ok = skew <= MAX_SNAPSHOT_SKEW_SECONDS
                data_ok = bool(fresh and snapshot_ok and net_profit > 0)
                market_status = "داده بازار مناسب شبیه‌سازی" if data_ok else "نیازمند بررسی داده/زمان"
                validation_status = "فقط شبیه‌سازی؛ انتقال/شبکه تأییدنشده" if data_ok else market_status
                total_costs = buy_fee_cost + buy_slippage_cost + sell_fee_cost + sell_slippage_cost + transfer_cost

                opportunities.append({
                    "symbol": symbol, "buy_exchange": buy_name, "sell_exchange": sell_name,
                    "buy_ask": best_ask, "sell_bid": best_bid, "spread_pct": round(spread_pct, 4),
                    "net_spread_pct": round(net_pct, 4), "profit_toman": round(net_profit),
                    "stress_profit_slip_010_toman": round(stress[0.10]),
                    "stress_profit_slip_025_toman": round(stress[0.25]),
                    "stress_profit_slip_050_toman": round(stress[0.50]),
                    "max_extra_slippage_pct": round(max_extra, 4),
                    "used_capital_toman": round(used_capital),
                    "unused_capital_toman": round(max(0, capital_toman - used_capital)),
                    "base_quantity": bought_qty, "buy_vwap": round(buy_vwap, 8),
                    "sell_vwap": round(sell_vwap, 8),
                    "buy_levels_used": levels_required(buy_book["asks"], bought_qty),
                    "sell_levels_used": sell_levels_used,
                    "depth_coverage_pct": round(min(100.0, sold_qty / sell_qty * 100), 2),
                    "buy_book_age_seconds": round(effective_buy_age, 2),
                    "sell_book_age_seconds": round(effective_sell_age, 2),
                    "snapshot_skew_seconds": round(skew, 2),
                    "buy_api_latency_ms": buy_book["latency_ms"],
                    "sell_api_latency_ms": sell_book["latency_ms"],
                    "data_ok": data_ok, "validation_status": validation_status,
                    "market_data_status": market_status, "fixed_fee_coin": fixed_fee,
                    "transfer_pct_applied": transfer_pct,
                    "transfer_mode": f"ثابت: {fixed_fee:g} {base}" if fixed_fee is not None else "درصدی (تخمینی)",
                    "asset_identity_status": "تأییدنشده؛ تطبیق نماد به‌تنهایی کافی نیست",
                    "network_status": "نامشخص؛ شبکه مشترک و آدرس/ممو بررسی نشده",
                    "deposit_withdraw_status": "نامشخص؛ وضعیت واریز/برداشت صرافی‌ها بررسی نشده",
                    "execution_ready": False,
                    "buy_gross_toman": round(raw_buy_cost), "sell_gross_toman": round(raw_sell_value),
                    "buy_fee_toman": round(buy_fee_cost), "buy_slippage_toman": round(buy_slippage_cost),
                    "sell_fee_toman": round(sell_fee_cost), "sell_slippage_toman": round(sell_slippage_cost),
                    "transfer_cost_toman": round(transfer_cost), "total_costs_toman": round(total_costs),
                    "gross_profit_toman": round(net_profit + total_costs),
                    "depth_note": (
                        f"مهر صرافی: خرید {effective_buy_age:.1f}s / فروش {effective_sell_age:.1f}s؛ "
                        "زمان والکس فقط زمان دریافت محلی است"
                    ),
                    "note": "محاسبه بر اساس سطوح قابل مشاهده دفتر سفارش؛ موجودی و انتقال تأیید نشده",
                })
    opportunities.sort(key=lambda item: item["profit_toman"], reverse=True)
    return {"opportunities": opportunities, "errors": errors, "diagnostics": diagnostics}
