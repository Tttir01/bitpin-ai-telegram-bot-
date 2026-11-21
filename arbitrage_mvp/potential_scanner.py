"""پایش فرصت احتمالی با زمان دریافت کلاینت؛ هرگز سیگنال تأییدشده تولید نمی‌کند."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from time import perf_counter_ns
import time

from scanner import (
    WALLEX, NOBITEX, HEADERS, get_json, normalize_symbol, _levels,
    _timestamp, _buy, _sell,
)


def _fetch_one(name, url, parser, timeout):
    started_at = datetime.now(timezone.utc)
    started_ns = perf_counter_ns()
    payload = get_json(url, timeout=timeout)
    ended_ns = perf_counter_ns()
    received_at = datetime.now(timezone.utc)
    books = parser(payload)
    return {
        "exchange": name,
        "books": books,
        "request_started_at_utc": started_at.isoformat(),
        "received_at_utc": received_at.isoformat(),
        "request_duration_ms": (ended_ns - started_ns) / 1_000_000,
        "received_monotonic_ns": ended_ns,
    }


def _parse_wallex(payload):
    if payload.get("success") is not True:
        raise ValueError("پاسخ دفتر سفارش والکس موفق نبود.")
    data = payload.get("result") or payload.get("data") or {}
    if isinstance(data, dict) and isinstance(data.get("symbols"), dict):
        data = data["symbols"]
    books = {}
    for raw_symbol, item in data.items():
        if not isinstance(item, dict):
            continue
        symbol = normalize_symbol(raw_symbol, ("USDT", "USDC", "TMN", "IRT", "BTC", "ETH"))
        asks = _levels(item.get("ask") or item.get("asks"), "ask")
        bids = _levels(item.get("bid") or item.get("bids"), "bid")
        if asks and bids:
            books[symbol] = {
                "asks": asks, "bids": bids,
                # این مقدار فقط از payload رسمی می‌آید؛ زمان دریافت جایگزین آن نیست.
                "exchange_timestamp": _timestamp(item),
            }
    if not books:
        raise ValueError("دفتر سفارش قابل استفاده از والکس دریافت نشد.")
    return books


def _parse_nobitex(payload, irt_divisor):
    if payload.get("status") != "ok":
        raise ValueError("پاسخ دفتر سفارش نوبیتکس موفق نبود.")
    books = {}
    for raw_symbol, item in payload.items():
        if raw_symbol in {"status", "message"} or not isinstance(item, dict):
            continue
        symbol = normalize_symbol(raw_symbol, ("USDT", "USDC", "IRT", "RLS", "BTC", "ETH"))
        asks = _levels(item.get("asks"), "ask")
        bids = _levels(item.get("bids"), "bid")
        if not asks or not bids:
            continue
        divisor = irt_divisor if symbol.endswith("/IRT") else 1.0
        books[symbol] = {
            "asks": [(p / divisor, q) for p, q in asks],
            "bids": [(p / divisor, q) for p, q in bids],
            "exchange_timestamp": _timestamp(item),
        }
    if not books:
        raise ValueError("دفتر سفارش قابل استفاده از نوبیتکس دریافت نشد.")
    return books


def _collect(settings):
    jobs = {
        "Wallex": (f"{WALLEX}/v2/depth/all", _parse_wallex),
        "Nobitex": (f"{NOBITEX}/v3/orderbook/all",
                    lambda p: _parse_nobitex(p, settings.nobitex_irt_price_divisor)),
    }
    results, errors = {}, []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            pool.submit(_fetch_one, name, url, parser, settings.request_timeout_seconds): name
            for name, (url, parser) in jobs.items()
        }
        for future, name in [(f, n) for f, n in futures.items()]:
            try:
                results[name] = future.result()
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
    return results, errors


def scan_potential(settings, max_receive_skew_seconds=5.0, max_request_duration_seconds=10.0):
    """فقط candidate پژوهشی؛ هیچ candidateای را eligible/verified نمی‌کند."""
    feeds, errors = _collect(settings)
    if len(feeds) != 2:
        return {
            "status": "REJECTED_STALE_OR_INVALID", "potential_opportunities": [],
            "feed_metadata": feeds, "errors": errors,
        }

    wallex, nobitex = feeds["Wallex"], feeds["Nobitex"]
    receive_w = datetime.fromisoformat(wallex["received_at_utc"])
    receive_n = datetime.fromisoformat(nobitex["received_at_utc"])
    receive_skew = abs((receive_w - receive_n).total_seconds())
    durations_ok = all(
        feed["request_duration_ms"] <= max_request_duration_seconds * 1000
        for feed in feeds.values()
    )
    receive_skew_ok = receive_skew <= max_receive_skew_seconds
    opportunities = []

    fee_w = settings.wallex_fee_pct / 100
    fee_n = settings.nobitex_fee_pct / 100
    slip = settings.slippage_pct_per_side / 100
    transfer = settings.transfer_cost_pct / 100

    common = sorted(set(wallex["books"]) & set(nobitex["books"]))
    for symbol in common:
        if not symbol.endswith("/IRT"):
            continue
        for buy_name, buy_feed, buy_fee, sell_name, sell_feed, sell_fee in (
            ("Wallex", wallex, fee_w, "Nobitex", nobitex, fee_n),
            ("Nobitex", nobitex, fee_n, "Wallex", wallex, fee_w),
        ):
            buy_book = buy_feed["books"][symbol]
            sell_book = sell_feed["books"][symbol]
            sell_depth = sum(q for _, q in sell_book["bids"])
            budget = settings.capital_toman / (1 + transfer)
            qty, buy_gross = _buy(buy_book["asks"], budget, sell_depth, buy_fee, slip)
            sold, sell_gross = _sell(sell_book["bids"], qty)
            if qty <= 0 or sold + max(1e-12, qty * 1e-8) < qty:
                continue
            buy_cost = buy_gross * (1 + buy_fee) * (1 + slip)
            sell_net = sell_gross * (1 - sell_fee) * (1 - slip)
            transfer_cost = buy_gross * transfer
            net = sell_net - buy_cost - transfer_cost
            if net < settings.min_net_profit_toman:
                continue
            opportunities.append({
                "symbol": symbol, "buy_exchange": buy_name, "sell_exchange": sell_name,
                "quantity": qty, "estimated_net_profit_toman": net,
                "buy_vwap": buy_gross / qty, "sell_vwap": sell_gross / sold,
                "status": "POTENTIAL_ONLY_LOCAL_RECEIVE_TIME",
                "label": "فرصت احتمالی؛ زمان دریافت محلی؛ تأییدنشده و غیرقابل معامله",
                "exchange_timestamps_present": (
                    buy_book["exchange_timestamp"] is not None
                    and sell_book["exchange_timestamp"] is not None
                ),
                "receive_skew_seconds": receive_skew,
                "transport_quality_ok": receive_skew_ok and durations_ok,
                "verified": False,
                "eligible": False,
                "execution_allowed": False,
            })

    for item in opportunities:
        if not item["transport_quality_ok"]:
            item["status"] = "REJECTED_STALE_OR_INVALID"
            item["label"] = "داده دریافتی نامتقارن/کند؛ فقط ثبت تشخیصی"
    return {
        "status": "POTENTIAL_ONLY_LOCAL_RECEIVE_TIME",
        "potential_opportunities": opportunities,
        "feed_metadata": feeds,
        "errors": errors,
        "common_symbols": len(common),
        "receive_skew_seconds": receive_skew,
        "receive_skew_ok": receive_skew_ok,
        "request_durations_ok": durations_ok,
        "limitations": [
            "received_at_utc زمان دریافت کلاینت است، نه timestamp صرافی",
            "زمان دریافت تازه بودن داده در سمت صرافی یا هم‌زمانی واقعی دفترها را ثابت نمی‌کند",
            "این خروجی صرفاً پایش پژوهشی است و مجوز معامله نیست",
        ],
    }
