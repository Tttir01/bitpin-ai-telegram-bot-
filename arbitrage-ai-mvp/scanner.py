import requests

BITPIN = "https://api.bitpin.org/api/v1"
BINANCE = "https://data-api.binance.vision/api/v3"

def get_json(url):
    r = requests.get(url, timeout=15, headers={"User-Agent":"ArbitrageAI-MVP/0.1"})
    r.raise_for_status()
    return r.json()

def rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("results", "data", "items", "tickers", "markets"):
            if isinstance(payload.get(k), list):
                return payload[k]
    return []

def val(d, *keys):
    for k in keys:
        try:
            if d.get(k) not in (None, ""):
                return float(d[k])
        except (TypeError, ValueError):
            pass
    return None

def bitpin_data():
    out = {}
    for x in rows(get_json(f"{BITPIN}/mkt/tickers/")):
        if not isinstance(x, dict):
            continue
        s = str(x.get("symbol") or x.get("market") or x.get("code") or "").upper().replace("_","/").replace("-","/")
        if "/" not in s:
            for q in ("USDT","USDC","BTC","ETH","IRT","IRR"):
                if s.endswith(q) and len(s) > len(q):
                    s = s[:-len(q)] + "/" + q
                    break
        last = val(x, "last","price","close","last_price")
        bid, ask = val(x,"bid","best_bid"), val(x,"ask","best_ask")
        if s and last and last > 0:
            out[s] = {"bid":bid or last, "ask":ask or last}
    return out

def binance_data():
    out = {}
    for x in get_json(f"{BINANCE}/ticker/bookTicker"):
        s = str(x.get("symbol","")).upper()
        for q in ("USDT","USDC","BTC","ETH","FDUSD","EUR"):
            if s.endswith(q) and len(s) > len(q):
                bid, ask = val(x,"bidPrice"), val(x,"askPrice")
                if bid and ask:
                    out[s[:-len(q)] + "/" + q] = {"bid":bid,"ask":ask}
                break
    return out

def scan_markets(fee_local=0.0025, fee_global=0.001):
    errors, opps = [], []
    try: local = bitpin_data()
    except Exception as e:
        local = {}; errors.append(f"Bitpin API: {type(e).__name__}: {e}")
    try: global_ = binance_data()
    except Exception as e:
        global_ = {}; errors.append(f"Binance API: {type(e).__name__}: {e}")
    for symbol in sorted(set(local) & set(global_)):
        venues = [("Bitpin",local[symbol],fee_local),("Binance",global_[symbol],fee_global)]
        for buy_name,buy,buy_fee in venues:
            for sell_name,sell,sell_fee in venues:
                if buy_name == sell_name: continue
                ask, bid = buy["ask"], sell["bid"]
                if not ask or not bid or ask <= 0: continue
                raw = (bid/ask - 1)*100
                net = ((bid*(1-sell_fee))/(ask*(1+buy_fee))-1)*100
                if raw > 0:
                    opps.append({"symbol":symbol,"buy_exchange":buy_name,"sell_exchange":sell_name,
                    "buy_ask":ask,"sell_bid":bid,"spread_pct":round(raw,4),
                    "net_spread_pct":round(net,4),"note":"داده ticker؛ بدون هزینه انتقال و عمق سفارش"})
    return {"opportunities":opps,"errors":errors}
