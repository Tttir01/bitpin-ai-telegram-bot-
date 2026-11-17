import requests

BITPIN = "https://api.bitpin.org/api/v1"
BINANCE = "https://data-api.binance.vision/api/v3"


def get_json(url):
    response = requests.get(
        url, timeout=15, headers={"User-Agent": "ArbitrageAI-MVP/0.2"}
    )
    response.raise_for_status()
    return response.json()


def rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "data", "items", "tickers", "markets"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def val(data, *keys):
    for key in keys:
        try:
            if data.get(key) not in (None, ""):
                number = float(data[key])
                if number > 0:
                    return number
        except (TypeError, ValueError):
            pass
    return None


def bitpin_data():
    markets = {}
    for item in rows(get_json(f"{BITPIN}/mkt/tickers/")):
        if not isinstance(item, dict):
            continue
        symbol = str(
            item.get("symbol") or item.get("market") or item.get("code") or ""
        ).upper().replace("_", "/").replace("-", "/")
        if "/" not in symbol:
            for quote in ("USDT", "USDC", "BTC", "ETH", "IRT", "IRR"):
                if symbol.endswith(quote) and len(symbol) > len(quote):
                    symbol = symbol[:-len(quote)] + "/" + quote
                    break
        last = val(item, "last", "price", "close", "last_price")
        bid = val(item, "bid", "best_bid")
        ask = val(item, "ask", "best_ask")
        if symbol and last:
            markets[symbol] = {"bid": bid or last, "ask": ask or last}
    return markets


def binance_data():
    markets = {}
    payload = get_json(f"{BINANCE}/ticker/bookTicker")
    for item in payload:
        symbol = str(item.get("symbol", "")).upper()
        for quote in ("USDT", "USDC", "BTC", "ETH", "FDUSD", "EUR"):
            if symbol.endswith(quote) and len(symbol) > len(quote):
                bid = val(item, "bidPrice")
                ask = val(item, "askPrice")
                if bid and ask:
                    markets[symbol[:-len(quote)] + "/" + quote] = {
                        "bid": bid, "ask": ask
                    }
                break
    return markets


def scan_markets(
    fee_local=0.0025,
    fee_global=0.001,
    slippage_pct=0.20,
    transfer_cost_pct=0.30,
):
    """
    slippage_pct: estimated slippage on EACH side, in percent.
    transfer_cost_pct: estimated total transfer/other cost as percent of buy notional.
    The estimates are user inputs, not measured execution costs.
    """
    errors, opportunities = [], []
    try:
        local = bitpin_data()
    except Exception as error:
        local = {}
        errors.append(f"Bitpin API: {type(error).__name__}: {error}")
    try:
        global_markets = binance_data()
    except Exception as error:
        global_markets = {}
        errors.append(f"Binance API: {type(error).__name__}: {error}")

    slippage = max(0.0, float(slippage_pct)) / 100
    transfer_cost = max(0.0, float(transfer_cost_pct)) / 100

    for symbol in sorted(set(local) & set(global_markets)):
        venues = [
            ("Bitpin", local[symbol], fee_local),
            ("Binance", global_markets[symbol], fee_global),
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
                        "estimated_cost_pct": round(
                            (raw_pct - net_pct), 4
                        ),
                        "note": (
                            "برآوردی؛ لغزش و انتقال دستی‌اند؛ "
                            "عمق سفارش و امکان انتقال زنده تأیید نشده"
                        ),
                    })

    opportunities.sort(
        key=lambda item: item["net_spread_pct"], reverse=True
    )
    return {"opportunities": opportunities, "errors": errors}
