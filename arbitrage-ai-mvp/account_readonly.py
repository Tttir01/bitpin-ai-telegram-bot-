"""Read-only authenticated account access for Wallex and Nobitex.

Only GET requests are used. This module deliberately contains no order,
transfer, deposit, or withdrawal operations.
"""
import os
from decimal import Decimal, InvalidOperation
import requests

WALLEX_URL = "https://api.wallex.ir"
NOBITEX_URL = "https://apiv2.nobitex.ir"
TIMEOUT = (5, 15)
HEADERS = {"User-Agent": "ArbitrageAI-ReadOnly/1.0", "Accept": "application/json"}

class ExchangeAPIError(RuntimeError):
    pass

def _decimal(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else Decimal("0")
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")

def _get_json(url, headers):
    try:
        response = requests.get(url, headers={**HEADERS, **headers}, timeout=TIMEOUT)
        if response.status_code == 401:
            raise ExchangeAPIError("احراز هویت ناموفق است؛ کلید یا توکن را بررسی کنید.")
        if response.status_code == 403:
            raise ExchangeAPIError("دسترسی خواندن موجودی مجاز نیست؛ مجوز API را بررسی کنید.")
        if response.status_code == 429:
            raise ExchangeAPIError("محدودیت درخواست صرافی؛ کمی بعد دوباره تلاش کنید.")
        response.raise_for_status()
        payload = response.json()
    except ExchangeAPIError:
        raise
    except requests.Timeout as error:
        raise ExchangeAPIError("مهلت پاسخ صرافی تمام شد؛ دوباره تلاش کنید.") from error
    except requests.RequestException as error:
        raise ExchangeAPIError("ارتباط با API صرافی برقرار نشد.") from error
    except ValueError as error:
        raise ExchangeAPIError("پاسخ صرافی JSON معتبر نیست.") from error
    if not isinstance(payload, dict):
        raise ExchangeAPIError("ساختار پاسخ صرافی معتبر نیست.")
    return payload

def wallex_balances(api_key=None):
    api_key = (api_key or os.getenv("WALLEX_API_KEY", "")).strip()
    if not api_key:
        raise ExchangeAPIError("کلید خواندن والکس تنظیم نشده است.")
    payload = _get_json(f"{WALLEX_URL}/v1/account/balances", {"X-API-Key": api_key})
    if payload.get("success") is not True:
        raise ExchangeAPIError("والکس دریافت موجودی را تأیید نکرد.")
    balances = (payload.get("result") or {}).get("balances")
    if not isinstance(balances, dict):
        raise ExchangeAPIError("ساختار موجودی والکس قابل شناسایی نیست.")
    rows = []
    for symbol, item in balances.items():
        if not isinstance(item, dict):
            continue
        total, locked = _decimal(item.get("value")), _decimal(item.get("locked"))
        if total == 0 and locked == 0:
            continue
        rows.append({
            "asset": str(item.get("asset") or symbol).upper(),
            "name": str(item.get("faName") or item.get("asset") or symbol),
            "total": total, "locked": locked,
            "available": max(Decimal("0"), total - locked), "exchange": "والکس",
        })
    return sorted(rows, key=lambda row: row["asset"])

def nobitex_balances(api_token=None):
    api_token = (api_token or os.getenv("NOBITEX_API_TOKEN", "")).strip()
    if not api_token:
        raise ExchangeAPIError("توکن خواندن نوبیتکس تنظیم نشده است.")
    payload = _get_json(
        f"{NOBITEX_URL}/users/wallets/list",
        {"Authorization": f"Token {api_token}"},
    )
    if payload.get("status") != "ok":
        raise ExchangeAPIError("نوبیتکس دریافت موجودی را تأیید نکرد.")
    wallets = payload.get("wallets")
    if not isinstance(wallets, list):
        raise ExchangeAPIError("ساختار کیف‌پول‌های نوبیتکس قابل شناسایی نیست.")
    rows = []
    for wallet in wallets:
        if not isinstance(wallet, dict):
            continue
        asset = str(wallet.get("currency") or "").upper()
        total = _decimal(wallet.get("balance"))
        locked = _decimal(wallet.get("blockedBalance"))
        available = _decimal(wallet.get("activeBalance"))
        if not asset or (total == 0 and locked == 0 and available == 0):
            continue
        if asset == "RLS":
            total /= Decimal("10")
            locked /= Decimal("10")
            available /= Decimal("10")
            asset = "IRT"
        rows.append({
            "asset": asset, "name": "تومان" if asset == "IRT" else asset,
            "total": total, "locked": locked, "available": available,
            "exchange": "نوبیتکس",
        })
    return sorted(rows, key=lambda row: row["asset"])
