import time
import requests

# Wallex public market data; these endpoints do not require an API key.
WALLEX = "https://api.wallex.ir"
NOBITEX = "https://apiv2.nobitex.ir"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ArbitrageAI/0.5)",
    "Accept": "application/json",
}


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


def rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "data", "items", "tickers", "markets"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                return rows(value)
    return []


def val(data, *keys):
    for key in keys:
        try:
            value = data.get(key)
            if value not in (None, ""):
                number = float(value)
                if number > 0:
                    return number
        except (TypeError, ValueError, AttributeError):
            pass
    return None


def normalize_symbol(raw, quotes):
    symbol = str(raw or "").upper().replace("_", "/").replace("-", "/")
    if "/" not in symbol:
        for quote in sorted(quotes, key=len, reverse=True):
            if symbol.endswith(quote) and len(symbol) > len(quote):
                return symbol[:-len(quote)] + "/" + quote
    return symbol


def wallex_data():
    payload = get_json(f"{WALLEX}/v1/markets")
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise RuntimeError("پاسخ فهرست بازارهای عمومی والکس معتبر نیست.")

    result = payload.get("result") or {}
    symbols = result.get("symbols") or {}
    if not isinstance(symbols, dict):
        raise RuntimeError("ساختار فهرست نمادهای والکس قابل شناسایی نیست.")

    markets = {}
    for raw_symbol, item in symbols.items():
        if not isinstance(item, dict):
            continue
        symbol = normalize_symbol(
            item.get("symbol") or raw_symbol,
            ("USDT", "USDC", "TMN", "IRT", "IRR", "BTC", "ETH"),
        )
        # Wallex uses TMN (Toman). Normalize it to IRT as the app's
        # common Toman-denominated comparison key; no price scaling is needed.
        symbol = symbol.replace("/TMN", "/IRT")
        stats = item.get("stats") or {}
        bid = val(stats, "bidPrice", "bid")
        ask = val(stats, "askPrice", "ask")
        if symbol and bid and ask:
            markets[symbol] = {"bid": bid, "ask": ask}
    if not markets:
        raise RuntimeError("از والکس داده معتبر قیمت خرید و فروش دریافت نشد.")
    return markets


def nobitex_data():
    # Official public endpoint: no token required. /all returns all order books.
    payload = get_json(f"{NOBITEX}/v3/orderbook/all")
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise RuntimeError("پاسخ دفتر سفارش عمومی نوبیتکس معتبر نیست.")

    markets = {}
    quotes = ("USDT", "USDC", "IRT", "RLS", "BTC", "ETH")
    for raw_symbol, book in payload.items():
        if raw_symbol in ("status", "message") or not isinstance(book, dict):
            continue
        symbol = normalize_symbol(raw_symbol, quotes)
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        try:
            best_bid = max((float(level[0]), float(level[1])) for level in bids if len(level) >= 2)
            best_ask = min((float(level[0]), float(level[1])) for level in asks if len(level) >= 2)
        except (ValueError, TypeError):
            continue
        if best_bid[0] <= 0 or best_ask[0] <= 0:
            continue

        # Nobitex quotes IRT market prices in Rial; convert to Toman.
        divisor = 10.0 if symbol.endswith("/IRT") else 1.0
        markets[symbol] = {
            "bid": best_bid[0] / divisor,
            "ask": best_ask[0] / divisor,
            "bid_qty": best_bid[1],
            "ask_qty": best_ask[1],
        }
    if not markets:
        raise RuntimeError("از نوبیتکس دفتر سفارش معتبر دریافت نشد.")
    return markets


def scan_markets(
    fee_local=0.0025,
    fee_global=0.0025,
    slippage_pct=0.20,
    transfer_cost_pct=0.30,
):
    """Public-data simulation only. No account balances, transfers, or live orders."""
    errors, opportunities = [], []
    try:
        local = wallex_data()
    except Exception as error:
        local = {}
        errors.append(f"Wallex API: {type(error).__name__}: {error}")
    try:
        nobitex = nobitex_data()
    except Exception as error:
        nobitex = {}
        errors.append(f"Nobitex API: {type(error).__name__}: {error}")

    slippage = max(0.0, float(slippage_pct)) / 100
    transfer_cost = max(0.0, float(transfer_cost_pct)) / 100

    for symbol in sorted(set(local) & set(nobitex)):
        venues = [
            ("Wallex", local[symbol], fee_local),
            ("Nobitex", nobitex[symbol], fee_global),
        ]
        for buy_name, buy, buy_fee in venues:
            for sell_name, sell, sell_fee in venues:
                if buy_name == sell_name:
                    continue
                ask, bid = buy["ask"], sell["bid"]
                if not ask or not bid or ask <= 0:
                    continue

                raw_pct = (bid / ask - 1) * 100
                buy_cost = ask * (1 + buy_fee) * (1 + slippage)
                sell_proceeds = bid * (1 - sell_fee) * (1 - slippage)
                net_pct = (sell_proceeds / buy_cost - 1) * 100 - transfer_cost_pct

                if raw_pct > 0:
                    opportunities.append({
                        "symbol": symbol,
                        "buy_exchange": buy_name,
                        "sell_exchange": sell_name,
                        "buy_ask": ask,
                        "sell_bid": bid,
                        "spread_pct": round(raw_pct, 4),
                        "net_spread_pct": round(net_pct, 4),
                        "estimated_cost_pct": round(raw_pct - net_pct, 4),
                        "note": (
                            "قیمت‌های برتر اعلام‌شده؛ حجم قابل اجرا، موجودی، انتقال و اجرای "
                            "سفارش هنوز در این نسخه تأیید نمی‌شود"
                        ),
                    })

    opportunities.sort(key=lambda item: item["net_spread_pct"], reverse=True)
    return {"opportunities": opportunities, "errors": errors}
