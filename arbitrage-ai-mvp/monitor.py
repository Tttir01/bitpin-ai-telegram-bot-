import json
import os
import time
from pathlib import Path

import requests
from scanner import scan_markets

CAPITAL_TOMAN = float(os.getenv("CAPITAL_TOMAN", "2000000"))
MIN_NET_PROFIT_PCT = float(os.getenv("MIN_NET_PROFIT_PCT", "0.25"))
FEE_WALLEX = float(os.getenv("FEE_WALLEX", "0.25")) / 100
FEE_NOBITEX = float(os.getenv("FEE_NOBITEX", "0.25")) / 100
SLIPPAGE_PCT = float(os.getenv("SLIPPAGE_PCT", "0.20"))
TRANSFER_COST_PCT = float(os.getenv("TRANSFER_COST_PCT", "0.30"))
COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "60"))
STATE_FILE = Path(os.getenv("ALERT_STATE_FILE", "/tmp/arbitrage_alert_state.json"))


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError as error:
        print(f"State persistence warning: {error}")


def send_telegram(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram alert skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not configured.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=(5, 15),
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API rejected the message: {payload}")
    return True


def main():
    print("Starting scheduled Wallex/Nobitex market scan...")
    result = scan_markets(
        fee_local=FEE_WALLEX,
        fee_global=FEE_NOBITEX,
        slippage_pct=SLIPPAGE_PCT,
        transfer_cost_pct=TRANSFER_COST_PCT,
        capital_toman=CAPITAL_TOMAN,
    )
    diagnostics = result.get("diagnostics", {})
    print(f"Books: Wallex={diagnostics.get('wallex_books', 0)}, "
          f"Nobitex={diagnostics.get('nobitex_books', 0)}, "
          f"common={diagnostics.get('common_symbols', 0)}")
    for error in result.get("errors", []):
        print(f"Market data error: {error}")

    candidates = [
        item for item in result.get("opportunities", [])
        if item.get("net_spread_pct", -999) >= MIN_NET_PROFIT_PCT
        and item.get("profit_toman", 0) > 0
    ]
    if not candidates:
        print("No net-positive opportunity passed the configured threshold.")
        return

    state = load_state()
    now = time.time()
    messages_sent = 0
    for item in candidates[:5]:
        key = "|".join((item["symbol"], item["buy_exchange"], item["sell_exchange"]))
        last_sent = float(state.get(key, 0) or 0)
        if now - last_sent < COOLDOWN_MINUTES * 60:
            continue

        message = (
            "🔔 فرصت آربیتراژ برای بررسی (فقط هشدار؛ بدون معامله)\n\n"
            f"جفت‌ارز: {item['symbol']}\n"
            f"خرید: {item['buy_exchange']} با قیمت حدودی {item['buy_ask']:,.0f} تومان\n"
            f"فروش: {item['sell_exchange']} با قیمت حدودی {item['sell_bid']:,.0f} تومان\n"
            f"بازده خالص تخمینی: {item['net_spread_pct']:.2f}%\n"
            f"سود خالص شبیه‌سازی: {item['profit_toman']:,.0f} تومان\n"
            f"سرمایه درگیر تخمینی: {item['used_capital_toman']:,.0f} تومان\n\n"
            "هشدار: موجودی حساب، امکان انتقال، کارمزد شبکه و اجرای واقعی تأیید نشده‌اند؛ "
            "قیمت‌ها ممکن است پیش از معامله تغییر کنند. هیچ سفارش یا انتقالی انجام نشده است."
        )
        if send_telegram(message):
            state[key] = now
            messages_sent += 1

    save_state(state)
    print(f"Completed. Telegram alerts sent: {messages_sent}; candidates: {len(candidates)}")


if __name__ == "__main__":
    main()
