import time
import requests

WALLEX = "https://api.wallex.ir"
NOBITEX = "https://apiv2.nobitex.ir"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ArbitrageAI/0.6)",
    "Accept": "application/json",
}
MAX_BOOK_AGE_SECONDS = 90


def get_json(url, retries=2):
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, timeout=(5, 18), headers=HEADERS)
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
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def parse_levels(levels, side):
    parsed = []
    for level in levels or []:
        try:
            if isinstance(level, dict):
                price = positive_float(level.get("price"))
                quantity = positive_float(level.get("quantity", level.get("qty")))
            else:
                price = positive_float(level[0])
                quantity = positive_float(level[1])
            if price and quantity:
                parsed.append((price, quantity))
        except (TypeError, ValueError, IndexError):
            continue
    return sorted(parsed, key=lambda x: x[0], reverse=(side == "bid"))


def wallex_books():
    payload = get_json(f"{WALLEX}/v2/depth/all")
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise RuntimeError("پاسخ دفتر سفارش عمومی والکس معتبر نیست.")
    result = payload.get("result") or payload.get("data") or {}
    if isinstance(result, dict) and isinstance(result.get("symbols"), dict):
        result = result["symbols"]
    books = {}
    for raw_symbol, book in result.items():
        if not isinstance(book, dict):
            continue
        symbol = normalize_symbol(raw_symbol, ("USDT", "USDC", "TMN", "IRT", "BTC", "ETH"))
        symbol = symbol.replace("/TMN", "/IRT")
        asks = parse_levels(book.get("ask") or book.get("asks"), "ask")
        bids = parse_levels(book.get("bid") or book.get("bids"), "bid")
        if asks and bids:
            books[symbol] = {
                "asks": asks, "bids": bids,
                "updated_at": None,
                "source": "Wallex",
            }
    if not books:
        raise RuntimeError("از دفتر سفارش عمومی والکس داده قابل استفاده دریافت نشد.")
    return books


def nobitex_books():
    payload = get_json(f"{NOBITEX}/v3/orderbook/all")
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise RuntimeError("پاسخ دفتر سفارش عمومی نوبیتکس معتبر نیست.")
    books = {}
    quotes = ("USDT", "USDC", "IRT", "RLS", "BTC", "ETH")
    for raw_symbol, book in payload.items():
        if raw_symbol in ("status", "message") or not isinstance(book, dict):
            continue
        symbol = normalize_symbol(raw_symbol, quotes)
        asks = parse_levels(book.get("asks"), "ask")
        bids = parse_levels(book.get("bids"), "bid")
        if not asks or not bids:
            continue
        # Nobitex IRT quotes are Rial; convert both price levels to Toman.
        divisor = 10.0 if symbol.endswith("/IRT") else 1.0
        asks = [(price / divisor, qty) for price, qty in asks]
        bids = [(price / divisor, qty) for price, qty in bids]
        updated = book.get("lastUpdate")
        try:
            updated = float(updated) / 1000 if updated else None
        except (TypeError, ValueError):
            updated = None
        books[symbol] = {
            "asks": asks, "bids": bids,
            "updated_at": updated,
            "source": "Nobitex",
        }
    if not books:
        raise RuntimeError("از دفتر سفارش عمومی نوبیتکس داده قابل استفاده دریافت نشد.")
    return books


def buy_from_asks(asks, quote_budget, max_base_qty, fee, slippage):
    remaining_budget = quote_budget
    remaining_qty = max_base_qty
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
    remaining = base_qty
    raw_proceeds = 0.0
    sold = 0.0
    for price, available in bids:
        if remaining <= 0:
            break
        qty = min(available, remaining)
        raw_proceeds += price * qty
        sold += qty
        remaining -= qty
    net_proceeds = raw_proceeds * (1 - fee) * (1 - slippage)
    return sold, raw_proceeds, net_proceeds


def scan_markets(
    fee_local=0.0025,
    fee_global=0.0025,
    slippage_pct=0.20,
    transfer_cost_pct=0.30,
    capital_toman=2_000_000,
    max_book_age_seconds=MAX_BOOK_AGE_SECONDS,
):
    """Depth-aware public-data simulation. No private keys, balances, transfers or live orders."""
    errors, opportunities, diagnostics = [], [], {}
    try:
        wallex = wallex_books()
    except Exception as error:
        wallex = {}
        errors.append(f"Wallex API: {type(error).__name__}: {error}")
    try:
        nobitex = nobitex_books()
    except Exception as error:
        nobitex = {}
        errors.append(f"Nobitex API: {type(error).__name__}: {error}")

    now = time.time()
    diagnostics["wallex_books"] = len(wallex)
    diagnostics["nobitex_books"] = len(nobitex)
    diagnostics["common_symbols"] = len(set(wallex) & set(nobitex))

    slippage = max(0.0, float(slippage_pct)) / 100
    transfer = max(0.0, float(transfer_cost_pct)) / 100
    fee_wallex = max(0.0, float(fee_local))
    fee_nobitex = max(0.0, float(fee_global))

    for symbol in sorted(set(wallex) & set(nobitex)):
        # Only Toman-quoted pairs can be converted to the user's Toman budget
        # without assuming a separate USDT conversion trade.
        if not symbol.endswith("/IRT"):
            continue
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
                buy_age = now - buy_book["updated_at"] if buy_book["updated_at"] else None
                sell_age = now - sell_book["updated_at"] if sell_book["updated_at"] else None
                # Nobitex exposes an exchange timestamp. Reject it when old;
                # Wallex depth response currently does not expose one.
                if any(age is not None and (age < -5 or age > max_book_age_seconds)
                       for age in (buy_age, sell_age)):
                    continue

                sell_depth_qty = sum(qty for _, qty in sell_book["bids"])
                if sell_depth_qty <= 0:
                    continue
                bought_qty, raw_buy_cost = buy_from_asks(
                    buy_book["asks"], capital_toman, sell_depth_qty,
                    buy_fee, slippage
                )
                if bought_qty <= 0:
                    continue
                sold_qty, raw_sell_value, net_sell_value = sell_into_bids(
                    sell_book["bids"], bought_qty, sell_fee, slippage
                )
                if sold_qty <= 0:
                    continue
                # Never report a partial buy as if all of it were sold.
                if sold_qty + max(1e-12, bought_qty * 1e-8) < bought_qty:
                    continue

                buy_debit = raw_buy_cost * (1 + buy_fee) * (1 + slippage)
                transfer_cost = raw_buy_cost * transfer
                net_profit = net_sell_value - buy_debit - transfer_cost
                used_capital = buy_debit + transfer_cost
                net_pct = (net_profit / used_capital * 100) if used_capital else -100
                if raw_buy_cost <= 0:
                    continue

                ages = [age for age in (buy_age, sell_age) if age is not None]
                age_label = (
                    f"مهر زمانی نوبیتکس: {max(ages):.0f} ثانیه"
                    if ages else "والکس زمان سرور اردربوک را اعلام نمی‌کند"
                )
                opportunities.append({
                    "symbol": symbol,
                    "buy_exchange": buy_name,
                    "sell_exchange": sell_name,
                    "buy_ask": buy_book["asks"][0][0],
                    "sell_bid": sell_book["bids"][0][0],
                    "spread_pct": round((sell_book["bids"][0][0] / buy_book["asks"][0][0] - 1) * 100, 4),
                    "net_spread_pct": round(net_pct, 4),
                    "estimated_cost_pct": round((1 - net_profit / raw_buy_cost) * 100, 4),
                    "profit_toman": round(net_profit),
                    "used_capital_toman": round(used_capital),
                    "unused_capital_toman": round(max(0, capital_toman - used_capital)),
                    "base_quantity": bought_qty,
                    "buy_gross_toman": round(raw_buy_cost),
                    "sell_gross_toman": round(raw_sell_value),
                    "depth_note": age_label,
                    "note": "محاسبه بر اساس سطوح قابل مشاهده دفتر سفارش؛ موجودی و انتقال تأیید نشده",
                })

    opportunities.sort(key=lambda item: item["profit_toman"], reverse=True)
    return {"opportunities": opportunities, "errors": errors, "diagnostics": diagnostics}
