"""اسکنر عمومی والکس/نوبیتکس؛ فقط GET و بدون کلید خصوصی."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
import requests

WALLEX = "https://api.wallex.ir"
NOBITEX = "https://apiv2.nobitex.ir"
HEADERS = {"Accept": "application/json", "User-Agent": "ArbitrageMVP-ReadOnly/1.0"}
RETRYABLE = {429, 500, 502, 503, 504}


def _retry_seconds(response, attempt):
    value = (getattr(response, "headers", {}) or {}).get("Retry-After")
    if value:
        try:
            return min(30.0, max(0.0, float(value)))
        except ValueError:
            try:
                dt = parsedate_to_datetime(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return min(30.0, max(0.0, (dt - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                pass
    return min(8.0, 2.0 ** attempt)


def get_json(url, timeout=15, retries=2):
    for attempt in range(retries + 1):
        response = requests.get(url, headers=HEADERS, timeout=(5, timeout))
        if response.status_code in RETRYABLE and attempt < retries:
            time.sleep(_retry_seconds(response, attempt))
            continue
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("پاسخ API ساختار JSON شیء ندارد.")
        return payload
    raise RuntimeError("دریافت داده پس از تلاش مجدد ناموفق بود.")


def _num(value):
    try:
        n = float(value)
        return n if n > 0 and n < float("inf") else None
    except (TypeError, ValueError):
        return None


def normalize_symbol(raw, quote_suffixes):
    s = str(raw or "").upper().replace("_", "/").replace("-", "/")
    if "/" not in s:
        for q in sorted(quote_suffixes, key=len, reverse=True):
            if s.endswith(q) and len(s) > len(q):
                s = s[:-len(q)] + "/" + q
                break
    return s.replace("/TMN", "/IRT").replace("/RLS", "/IRT")


def _levels(raw, side):
    rows = []
    for level in raw or []:
        try:
            if isinstance(level, dict):
                price = _num(level.get("price"))
                qty = _num(level.get("quantity", level.get("qty", level.get("amount"))))
            else:
                price, qty = _num(level[0]), _num(level[1])
            if price and qty:
                rows.append((price, qty))
        except (TypeError, IndexError):
            continue
    return sorted(rows, key=lambda x: x[0], reverse=(side == "bid"))


def _timestamp(book):
    for key in ("lastUpdate", "timestamp", "updatedAt", "updated_at", "time"):
        value = book.get(key) if isinstance(book, dict) else None
        if value is None:
            continue
        try:
            stamp = float(value)
            if stamp > 10**12:
                stamp /= 1000
            if stamp > 10**9:
                return stamp
        except (TypeError, ValueError):
            continue
    return None


def _book(asks, bids, received, stamp, source):
    return {"asks": asks, "bids": bids, "received_at": received,
            "exchange_timestamp": stamp, "source": source}


def fetch_wallex(timeout=15):
    received = time.time()
    payload = get_json(f"{WALLEX}/v2/depth/all", timeout)
    received = time.time()
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
            books[symbol] = _book(asks, bids, received, _timestamp(item), "Wallex")
    if not books:
        raise ValueError("دفتر سفارش قابل استفاده از والکس دریافت نشد.")
    return books


def fetch_nobitex(timeout=15, irt_divisor=10):
    received = time.time()
    payload = get_json(f"{NOBITEX}/v3/orderbook/all", timeout)
    received = time.time()
    if payload.get("status") != "ok":
        raise ValueError("پاسخ دفتر سفارش نوبیتکس موفق نبود.")
    books = {}
    suffixes = ("USDT", "USDC", "IRT", "RLS", "BTC", "ETH")
    for raw_symbol, item in payload.items():
        if raw_symbol in {"status", "message"} or not isinstance(item, dict):
            continue
        symbol = normalize_symbol(raw_symbol, suffixes)
        asks = _levels(item.get("asks"), "ask")
        bids = _levels(item.get("bids"), "bid")
        if not asks or not bids:
            continue
        # ضریب تبدیل قابل تنظیم است و باید با مستندات/نمونه قیمت همان روز تأیید شود.
        divisor = irt_divisor if symbol.endswith("/IRT") else 1.0
        asks = [(p / divisor, q) for p, q in asks]
        bids = [(p / divisor, q) for p, q in bids]
        books[symbol] = _book(asks, bids, received, _timestamp(item), "Nobitex")
    if not books:
        raise ValueError("دفتر سفارش قابل استفاده از نوبیتکس دریافت نشد.")
    return books


def _buy(asks, budget, max_qty, fee, slip):
    qty = cost = 0.0
    remaining = budget
    for price, available in asks:
        unit = price * (1 + fee) * (1 + slip)
        take = min(available, max_qty - qty, remaining / unit)
        if take <= 0:
            break
        qty += take
        cost += price * take
        remaining -= unit * take
    return qty, cost


def _sell(bids, quantity):
    sold = gross = 0.0
    for price, available in bids:
        take = min(available, quantity - sold)
        if take > 0:
            sold += take
            gross += price * take
        if sold >= quantity:
            break
    return sold, gross


def scan(settings):
    errors, opportunities = [], []
    try:
        wallex = fetch_wallex(settings.request_timeout_seconds)
    except Exception as exc:
        wallex = {}
        errors.append(f"Wallex: {type(exc).__name__}: {exc}")
    try:
        nobitex = fetch_nobitex(settings.request_timeout_seconds, settings.nobitex_irt_price_divisor)
    except Exception as exc:
        nobitex = {}
        errors.append(f"Nobitex: {type(exc).__name__}: {exc}")

    now = time.time()
    common = sorted(set(wallex) & set(nobitex))
    fee_w = settings.wallex_fee_pct / 100
    fee_n = settings.nobitex_fee_pct / 100
    slip = settings.slippage_pct_per_side / 100
    transfer = settings.transfer_cost_pct / 100
    for symbol in common:
        if not symbol.endswith("/IRT"):
            continue
        for buy_name, buy_book, buy_fee, sell_name, sell_book, sell_fee in (
            ("Wallex", wallex[symbol], fee_w, "Nobitex", nobitex[symbol], fee_n),
            ("Nobitex", nobitex[symbol], fee_n, "Wallex", wallex[symbol], fee_w),
        ):
            buy_stamp, sell_stamp = buy_book["exchange_timestamp"], sell_book["exchange_timestamp"]
            freshness_verified = buy_stamp is not None and sell_stamp is not None
            ages_ok = freshness_verified and 0 <= now - buy_stamp <= settings.max_book_age_seconds and 0 <= now - sell_stamp <= settings.max_book_age_seconds
            skew_ok = freshness_verified and abs(buy_stamp - sell_stamp) <= 15
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
            used = buy_cost + transfer_cost
            eligible = (ages_ok and skew_ok and net >= settings.min_net_profit_toman
                        and used <= settings.capital_toman and settings.fees_confirmed
                        and settings.transfer_cost_confirmed)
            reason = None
            if not freshness_verified:
                reason = "زمان سمت سرور در هر دو دفتر سفارش موجود نیست؛ تازگی قابل تأیید نیست"
            elif not ages_ok or not skew_ok:
                reason = "داده قدیمی یا اختلاف زمانی دو دفتر سفارش بیش از حد مجاز است"
            elif not settings.fees_confirmed:
                reason = "کارمزدهای واقعی حساب هنوز تأیید نشده‌اند"
            elif not settings.transfer_cost_confirmed:
                reason = "هزینه/مسیر انتقال هنوز تأیید نشده است"
            elif net < settings.min_net_profit_toman:
                reason = "سود خالص تخمینی کمتر از حداقل تنظیم‌شده است"
            elif used > settings.capital_toman:
                reason = "سرمایه موردنیاز بیش از سقف شبیه‌سازی است"
            opportunities.append({
                "symbol": symbol, "buy_exchange": buy_name, "sell_exchange": sell_name,
                "buy_vwap": buy_gross / qty, "sell_vwap": sell_gross / sold,
                "quantity": qty, "gross_profit_toman": sell_gross - buy_gross,
                "estimated_cost_toman": buy_cost - buy_gross + sell_gross - sell_net + transfer_cost,
                "estimated_net_profit_toman": net,
                "estimated_net_return_pct": net / used * 100 if used else 0,
                "freshness_verified": freshness_verified, "eligible": eligible,
                "rejection_reason": reason,
                "assumptions": {"wallex_fee_pct": settings.wallex_fee_pct,
                    "nobitex_fee_pct": settings.nobitex_fee_pct,
                    "slippage_pct_per_side": settings.slippage_pct_per_side,
                    "transfer_cost_pct": settings.transfer_cost_pct,
                    "fees_confirmed": settings.fees_confirmed,
                    "transfer_cost_confirmed": settings.transfer_cost_confirmed,
                    "nobitex_irt_price_divisor": settings.nobitex_irt_price_divisor,
                    "buy_book_timestamp": buy_stamp, "sell_book_timestamp": sell_stamp},
            })
    return {"wallex_books": len(wallex), "nobitex_books": len(nobitex),
            "common_symbols": len(common), "opportunities": opportunities,
            "accepted_count": sum(bool(x["eligible"]) for x in opportunities),
            "rejected_count": sum(not x["eligible"] for x in opportunities), "errors": errors}
