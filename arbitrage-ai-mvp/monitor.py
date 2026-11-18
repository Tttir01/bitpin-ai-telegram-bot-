import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from scanner import scan_markets

TEHRAN = ZoneInfo("Asia/Tehran")
CAPITAL_TOMAN = float(os.getenv("CAPITAL_TOMAN", "2000000"))
MIN_NET_PROFIT_PCT = float(os.getenv("MIN_NET_PROFIT_PCT", "0.25"))
FEE_WALLEX = float(os.getenv("FEE_WALLEX", "0.25")) / 100
FEE_NOBITEX = float(os.getenv("FEE_NOBITEX", "0.25")) / 100
SLIPPAGE_PCT = float(os.getenv("SLIPPAGE_PCT", "0.20"))
TRANSFER_COST_PCT = float(os.getenv("TRANSFER_COST_PCT", "0.30"))
COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "60"))
STATE_FILE = Path(os.getenv("ALERT_STATE_FILE", "/tmp/arbitrage_alert_state.json"))
MIN_STABLE_SCANS = 5
MAX_VWAP_CHANGE_PCT = 0.30
MAX_VOLUME_CHANGE_PCT = 25.0
MAX_PROFIT_DROP_PCT = 30.0


def load_state():
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "stability" in raw and "alerts" in raw:
            return raw
    except (OSError, ValueError):
        pass
    return {"alerts": {}, "stability": {}}


def save_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError as error:
        print(f"State persistence warning: {error}")


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram alert skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not configured.")
        return False
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
        timeout=(5, 15),
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram API rejected the message.")
    return True


def route_key(item):
    return "|".join((str(item.get("symbol", "")), str(item.get("buy_exchange", "")), str(item.get("sell_exchange", ""))))


def update_stability(candidates, state):
    previous = state.get("stability", {})
    current = {}
    counts = {}
    for item in candidates:
        key = route_key(item)
        snapshot = {
            "buy_vwap": float(item.get("buy_vwap") or item.get("buy_ask") or 0),
            "sell_vwap": float(item.get("sell_vwap") or item.get("sell_bid") or 0),
            "quantity": float(item.get("base_quantity") or 0),
            "profit": float(item.get("profit_toman") or 0),
        }
        old = previous.get(key)
        if old:
            def move(now_value, old_value):
                return abs(now_value / old_value - 1) * 100 if old_value else 999
            buy_move = move(snapshot["buy_vwap"], float(old.get("buy_vwap", 0)))
            sell_move = move(snapshot["sell_vwap"], float(old.get("sell_vwap", 0)))
            volume_move = move(snapshot["quantity"], float(old.get("quantity", 0)))
            profit_drop = (
                max(0.0, (float(old.get("profit", 0)) - snapshot["profit"]) / float(old["profit"]) * 100)
                if float(old.get("profit", 0)) > 0 else 0.0
            )
            stable = (
                buy_move <= MAX_VWAP_CHANGE_PCT
                and sell_move <= MAX_VWAP_CHANGE_PCT
                and volume_move <= MAX_VOLUME_CHANGE_PCT
                and profit_drop <= MAX_PROFIT_DROP_PCT
            )
            count = int(old.get("count", 1)) + 1 if stable else 1
        else:
            count = 1
        snapshot["count"] = count
        current[key] = snapshot
        counts[key] = count
    # A route missing from this scan loses its consecutive-stability streak.
    state["stability"] = current
    return counts


def format_opportunity(index, item, stable_count):
    return (
        f"{index}) {item.get('symbol', '—')} | خرید {item.get('buy_exchange', '—')} / فروش {item.get('sell_exchange', '—')}\n"
        f"میانگین خرید/فروش: {item.get('buy_vwap', item.get('buy_ask', 0)):,.8g} / "
        f"{item.get('sell_vwap', item.get('sell_bid', 0)):,.8g}\n"
        f"سرمایه: {item.get('used_capital_toman', 0):,.0f} تومان | "
        f"سود خالص تخمینی: {item.get('profit_toman', 0):,.0f} تومان "
        f"({item.get('net_spread_pct', 0):.3f}٪)\n"
        f"پایداری: {stable_count}/{MIN_STABLE_SCANS} اسکن | "
        f"پوشش عمق: {item.get('depth_coverage_pct', '—')}٪\n"
        f"هویت دارایی: {item.get('asset_identity_status', 'تأییدنشده')}\n"
        f"شبکه: {item.get('network_status', 'نامشخص')}\n"
        f"واریز/برداشت: {item.get('deposit_withdraw_status', 'نامشخص')}\n"
        "آمادگی اجرای واقعی: خیر"
    )


def main():
    print("Starting scheduled Wallex/Nobitex market scan (simulation only)...")
    result = scan_markets(
        fee_local=FEE_WALLEX,
        fee_global=FEE_NOBITEX,
        slippage_pct=SLIPPAGE_PCT,
        transfer_cost_pct=TRANSFER_COST_PCT,
        capital_toman=CAPITAL_TOMAN,
    )
    diagnostics = result.get("diagnostics", {})
    print(
        f"Books: Wallex={diagnostics.get('wallex_books', 0)}, "
        f"Nobitex={diagnostics.get('nobitex_books', 0)}, "
        f"common={diagnostics.get('common_symbols', 0)}"
    )
    for error in result.get("errors", []):
        print(f"Market data error: {error}")

    candidates = [
        item for item in result.get("opportunities", [])
        if item.get("net_spread_pct", -999) >= MIN_NET_PROFIT_PCT
        and item.get("profit_toman", 0) > 0
        and item.get("used_capital_toman", 0) >= min(100000, CAPITAL_TOMAN)
    ]
    candidates.sort(key=lambda item: item.get("profit_toman", 0), reverse=True)

    state = load_state()
    stability_counts = update_stability(candidates, state)
    stable_candidates = [
        item for item in candidates
        if stability_counts.get(route_key(item), 0) >= MIN_STABLE_SCANS
    ]
    stable_candidates.sort(key=lambda item: item.get("profit_toman", 0), reverse=True)
    print(
        f"Eligible={len(candidates)}; stable for {MIN_STABLE_SCANS} scans="
        f"{len(stable_candidates)}"
    )

    now = time.time()
    alerts = state.setdefault("alerts", {})
    messages_sent = 0
    for item in stable_candidates[:5]:
        key = route_key(item)
        last_sent = float(alerts.get(key, 0) or 0)
        if now - last_sent < COOLDOWN_MINUTES * 60:
            continue
        message = (
            "🔔 فرصت پایدار آربیتراژ برای بررسی\n"
            f"زمان: {datetime.now(TEHRAN).strftime('%Y-%m-%d %H:%M:%S')}\n"
            "حالت: فقط تحلیل و شبیه‌سازی؛ بدون معامله واقعی\n\n"
            + format_opportunity(1, item, stability_counts.get(key, 0))
            + "\n\n⚠️ همه ارقام تخمینی‌اند؛ موجودی، هویت دارایی، شبکه و وضعیت واریز/برداشت تأیید نشده‌اند. "
            "این پیام توصیه خرید/فروش نیست."
        )
        try:
            if send_telegram(message):
                alerts[key] = now
                messages_sent += 1
        except (requests.RequestException, RuntimeError) as error:
            print(f"Telegram delivery failed: {type(error).__name__}: {error}")
            break

    today = datetime.now(TEHRAN).strftime("%Y-%m-%d")
    digest_key = f"daily_digest_{today}"
    if digest_key not in alerts:
        lines = [
            f"📊 گزارش روزانه پایش آربیتراژ | {today}",
            f"سرمایه شبیه‌سازی: {CAPITAL_TOMAN:,.0f} تومان",
            f"دفتر والکس: {diagnostics.get('wallex_books', '—')} | نوبیتکس: {diagnostics.get('nobitex_books', '—')}",
            f"جفت‌ارز مشترک: {diagnostics.get('common_symbols', '—')}",
            f"فرصت‌های واجد شرایط: {len(candidates)} | پایدار در ۵ اسکن: {len(stable_candidates)}",
            "فقط تحلیل و شبیه‌سازی؛ بدون سفارش واقعی",
            "",
        ]
        if stable_candidates:
            lines.append("بهترین فرصت‌های پایدار:")
            for index, item in enumerate(stable_candidates[:5], 1):
                lines.append(format_opportunity(index, item, stability_counts.get(route_key(item), 0)))
                lines.append("")
        else:
            lines.append("هنوز فرصتی در ۵ اسکن متوالی پایدار نمانده است.")
        lines.append("⚠️ انتقال، شبکه، موجودی و امکان اجرای واقعی تأیید نشده‌اند.")
        try:
            if send_telegram("\n".join(lines)):
                alerts[digest_key] = now
        except (requests.RequestException, RuntimeError) as error:
            print(f"Daily Telegram digest failed: {type(error).__name__}: {error}")

    save_state(state)
    print(f"Completed. Telegram alerts sent: {messages_sent}; stable candidates: {len(stable_candidates)}")


if __name__ == "__main__":
    main()
