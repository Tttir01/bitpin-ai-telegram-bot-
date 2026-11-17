import time
import requests

# Bitpin provides the same public REST API on these domains.
BITPIN_BASES = (
    "https://api.bitpin.org/api/v1",
    "https://api.bitpin.ir/api/v1",
    "https://api.bitpin.market/api/v1",
)
MEXC = "https://api.mexc.com/api/v3"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ArbitrageAI/0.3; +https://github.com/)",
    "Accept": "application/json",
}


def get_json(url, retries=2):
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, timeout=(5, 15), headers=HEADERS)
            # Retry transient rate-limit/server responses only.
            if response.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            last_error = error
            status = getattr(getattr(error, "response", None), "status_code", None)
            if status not in (None, 429, 500, 502, 503, 504) or attempt >= retries:
                raise
            time.sleep(1.0 * (attempt + 1))
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


def bitpin_data():
    last_error = None
    payload = None
    successful_base = None
    for base in BITPIN_BASES:
        try:
            payload = get_json(f"{base}/mkt/tickers/")
            successful_base = base
            break
        except requests.RequestException as error:
            last_error = error
            # Try the documented alternate Bitpin domains for access/routing errors.
            continue

    if payload is None:
        status = getattr(getattr(last_error, "response", None), "status_code", "network")
        raise RuntimeError(
            f"همه دامنه‌های عمومی بیت‌پین ناموفق بودند (آخرین وضعیت: {status}). "
            "اگر 403 باقی است، محدودیت IP/دسترسی سمت بیت‌پین یا میزبان را بررسی کنید."
        ) from last_error

    markets = {}
    for item in rows(payload):
        if not isinstance(item, dict):
            continue
        symbol = normalize_symbol(
            item.get("symbol") or item.get("market") or item.get("code"),
            ("USDT", "USDC", "BTC", "ETH", "IRT", "IRR"),
        )
        last = val(item, "last", "price", "close", "last_price")
        bid = val(item, "bid", "best_bid", "bid_price")
        ask = val(item, "ask", "best_ask", "ask_price")
        if symbol and last:
            markets[symbol] = {"bid": bid or last, "ask": ask or last}
    if not markets:
        raise RuntimeError(
            f"پاسخ {successful_base} دریافت شد، اما ساختار نمادها قابل شناسایی نبود."
        )
    return markets


def mexc_data():
    payload = get_json(f"{MEXC}/ticker/bookTicker")
    markets = {}
    for item in rows(payload):
        if not isinstance(item, dict):
            continue
        symbol = normalize_symbol(
            item.get("symbol"),
            ("USDT", "USDC", "BTC", "ETH", "EUR"),
        )
        bid = val(item, "bidPrice", "bid")
        ask = val(item, "askPrice", "ask")
        bid_qty = val(item, "bidQty", "bidSize")
        ask_qty = val(item, "askQty", "askSize")
        if symbol and bid and ask:
            markets[symbol] = {
                "bid": bid,
                "ask": ask,
                "bid_qty": bid_qty,
                "ask_qty": ask_qty,
            }
    if not markets:
        raise RuntimeError("MEXC پاسخی داد، اما داده معتبر دفتر سفارش دریافت نشد.")
    return markets


def scan_markets(
    fee_local=0.0025,
    fee_global=0.001,
    slippage_pct=0.20,
    transfer_cost_pct=0.30,
):
    """
    Public-data simulation only. No account balances, transfers, or live orders.
    Slippage is estimated on each side; transfer_cost_pct is a user estimate.
    """
    errors, opportunities = [], []
    try:
        local = bitpin_data()
    except Exception as error:
        local = {}
        errors.append(f"Bitpin API: {type(error).__name__}: {error}")
    try:
        global_markets = mexc_data()
    except Exception as error:
        global_markets = {}
        errors.append(f"MEXC API: {type(error).__name__}: {error}")

    slippage = max(0.0, float(slippage_pct)) / 100
    transfer_cost = max(0.0, float(transfer_cost_pct)) / 100

    for symbol in sorted(set(local) & set(global_markets)):
        venues = [
            ("Bitpin", local[symbol], fee_local),
            ("MEXC", global_markets[symbol], fee_global),
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
                            "شبیه‌سازی بر پایه بهترین قیمت؛ عمق کامل، موجودی، "
                            "انتقال و اجرای سفارش تأیید نشده"
                        ),
                    })

    opportunities.sort(key=lambda item: item["net_spread_pct"], reverse=True)
    return {"opportunities": opportunities, "errors": errors}
