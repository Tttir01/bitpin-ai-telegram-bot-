"""Independent scheduled market monitor with delayed order-book confirmation.

This process is separate from Streamlit. It only reads public order books,
records paper validations, and sends Telegram alerts; it never places orders.
"""
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
PAPER_COOLDOWN_MINUTES = int(os.getenv("PAPER_VALIDATION_COOLDOWN_MINUTES", "30"))
CONFIRM_DELAY_SECONDS = float(os.getenv("CONFIRM_DELAY_SECONDS", "5"))
STATE_FILE = Path(os.getenv("ALERT_STATE_FILE", ".cache/arbitrage_state.json"))
MIN_STABLE_SCANS = 5
MAX_VWAP_CHANGE_PCT = 0.10
MAX_VOLUME_CHANGE_PCT = 25.0
MAX_PROFIT_DROP_PCT = 30.0
# The external free scheduler runs hourly; tolerate normal scheduler jitter up to 90 minutes.
MAX_STABILITY_GAP_SECONDS = 90 * 60
MAX_LEDGER_ROWS = 500


def load_state():
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw.setdefault("alerts", {})
            raw.setdefault("stability", {})
            raw.setdefault("paper_validations", [])
            return raw
    except (OSError, ValueError):
        pass
    return {"alerts": {}, "stability": {}, "paper_validations": []}


def save_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temporary.replace(STATE_FILE)
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
    print("Telegram message delivered successfully.")
    return True


def route_key(item):
    return "|".join((
        str(item.get("symbol", "")),
        str(item.get("buy_exchange", "")),
        str(item.get("sell_exchange", "")),
    ))


def eligible_opportunities(result):
    """Reject stale or time-skewed books before any stability count or alert."""
    rows = []
    for item in result.get("opportunities", []):
        try:
            net_pct = float(item.get("net_spread_pct", -999))
            profit = float(item.get("profit_toman", 0))
            used = float(item.get("used_capital_toman", 0))
            buy_age = float(item.get("buy_book_age_seconds", float("inf")))
            sell_age = float(item.get("sell_book_age_seconds", float("inf")))
            skew = float(item.get("snapshot_skew_seconds", float("inf")))
        except (TypeError, ValueError, OverflowError):
            continue
        # Scanner must explicitly certify freshness and synchronized snapshots.
        if item.get("market_data_status") != "داده بازار مناسب شبیه‌سازی":
            continue
        if item.get("validation_status") != "فقط شبیه‌سازی؛ انتقال/شبکه تأییدنشده":
            continue
        if not all(map(lambda value: value == value and abs(value) != float("inf"),
                       (net_pct, profit, used, buy_age, sell_age, skew))):
            continue
        if (
            net_pct >= MIN_NET_PROFIT_PCT
            and profit > 0
            and 0 < used <= CAPITAL_TOMAN
            and 0 <= buy_age <= 90
            and 0 <= sell_age <= 90
            and 0 <= skew <= 15
        ):
            rows.append(item)
    return rows


def _move_pct(current, previous):
    try:
        current, previous = float(current), float(previous)
        if previous <= 0:
            return 999.0
        return abs(current / previous - 1) * 100
    except (TypeError, ValueError):
        return 999.0


def allowed_vwap_change_pct(net_spread_pct):
    """Use the tighter of 0.10% or half the route's net return."""
    try:
        margin = max(0.0, float(net_spread_pct))
    except (TypeError, ValueError):
        return 0.0
    return min(MAX_VWAP_CHANGE_PCT, margin / 2.0)


def confirm_snapshots(first_rows, second_rows):
    """Keep only routes still profitable and price-stable in the fresh scan."""
    second_by_key = {route_key(row): row for row in second_rows}
    confirmed = []
    rejected = []
    for first in first_rows:
        key = route_key(first)
        second = second_by_key.get(key)
        if second is None:
            rejected.append({"route": key, "reason": "route_missing_on_confirmation"})
            continue
        buy_move = _move_pct(second.get("buy_vwap"), first.get("buy_vwap"))
        sell_move = _move_pct(second.get("sell_vwap"), first.get("sell_vwap"))
        limit = allowed_vwap_change_pct(first.get("net_spread_pct", 0))
        try:
            second_profit = float(second.get("profit_toman", 0))
            second_net = float(second.get("net_spread_pct", -999))
        except (TypeError, ValueError):
            second_profit, second_net = 0.0, -999.0
        passed = (
            buy_move <= limit
            and sell_move <= limit
            and second_profit > 0
            and second_net >= MIN_NET_PROFIT_PCT
        )
        if passed:
            item = dict(second)
            item["confirmation_buy_move_pct"] = round(buy_move, 6)
            item["confirmation_sell_move_pct"] = round(sell_move, 6)
            item["confirmation_limit_pct"] = round(limit, 6)
            item["first_scan_profit_toman"] = first.get("profit_toman", 0)
            confirmed.append(item)
        else:
            rejected.append({
                "route": key,
                "reason": "price_moved_or_profit_disappeared",
                "buy_move_pct": round(buy_move, 6),
                "sell_move_pct": round(sell_move, 6),
                "allowed_move_pct": round(limit, 6),
                "second_profit_toman": second_profit,
            })
    return confirmed, rejected


def update_stability(candidates, state, now=None):
    """Count consecutive stable runs; reset after a long scheduler gap."""
    now = time.time() if now is None else float(now)
    previous = state.get("stability", {})
    current = {}
    counts = {}
    for item in candidates:
        key = route_key(item)
        snapshot = {
            "buy_vwap": float(item.get("buy_vwap") or 0),
            "sell_vwap": float(item.get("sell_vwap") or 0),
            "quantity": float(item.get("base_quantity") or 0),
            "profit": float(item.get("profit_toman") or 0),
            "timestamp": now,
        }
        old = previous.get(key)
        consecutive = False
        if old:
            try:
                if old.get("timestamp") is None:
                    raise ValueError("missing previous stability timestamp")
                elapsed = now - float(old["timestamp"])
                buy_move = _move_pct(snapshot["buy_vwap"], old.get("buy_vwap"))
                sell_move = _move_pct(snapshot["sell_vwap"], old.get("sell_vwap"))
                volume_move = _move_pct(snapshot["quantity"], old.get("quantity"))
                old_profit = float(old.get("profit", 0))
                profit_drop = (
                    max(0.0, (old_profit - snapshot["profit"]) / old_profit * 100)
                    if old_profit > 0 else 999.0
                )
                limit = allowed_vwap_change_pct(item.get("net_spread_pct", 0))
                consecutive = (
                    0 < elapsed <= MAX_STABILITY_GAP_SECONDS
                    and buy_move <= limit and sell_move <= limit
                    and volume_move <= MAX_VOLUME_CHANGE_PCT
                    and profit_drop <= MAX_PROFIT_DROP_PCT
                )
            except (TypeError, ValueError, OverflowError):
                consecutive = False
        count = int(old.get("count", 1)) + 1 if old and consecutive else 1
        snapshot["count"] = count
        current[key] = snapshot
        counts[key] = count
    # Missing routes and routes returning after a long gap restart at one.
    state["stability"] = current
    return counts

def record_paper_validations(candidates, state, now):
    """Record a validated public-book snapshot, not a claim of filled execution."""
    ledger = state.setdefault("paper_validations", [])
    last_by_key = {}
    for row in ledger:
        last_by_key[row.get("route", "")] = max(
            float(row.get("timestamp", 0) or 0),
            last_by_key.get(row.get("route", ""), 0),
        )
    added = []
    for item in candidates:
        key = route_key(item)
        if now - last_by_key.get(key, 0) < PAPER_COOLDOWN_MINUTES * 60:
            continue
        row = {
            "route": key,
            "timestamp": now,
            "time_tehran": datetime.fromtimestamp(now, TEHRAN).isoformat(),
            "capital_toman": round(float(item.get("used_capital_toman", 0))),
            "estimated_net_profit_toman": round(float(item.get("profit_toman", 0))),
            "estimated_net_return_pct": float(item.get("net_spread_pct", 0)),
            "buy_vwap": item.get("buy_vwap"),
            "sell_vwap": item.get("sell_vwap"),
            "confirmation_buy_move_pct": item.get("confirmation_buy_move_pct"),
            "confirmation_sell_move_pct": item.get("confirmation_sell_move_pct"),
            "status": "confirmed_public_orderbook_only",
            "real_order_placed": False,
        }
        ledger.append(row)
        added.append(row)
    state["paper_validations"] = ledger[-MAX_LEDGER_ROWS:]
    return added


def format_opportunity(index, item, stable_count):
    return (
        f"{index}) {item.get('symbol', '—')} | خرید {item.get('buy_exchange', '—')} / فروش {item.get('sell_exchange', '—')}\n"
        f"میانگین خرید/فروش: {item.get('buy_vwap', 0):,.8g} / {item.get('sell_vwap', 0):,.8g}\n"
        f"سرمایه: {item.get('used_capital_toman', 0):,.0f} تومان | سود خالص تخمینی: {item.get('profit_toman', 0):,.0f} تومان "
        f"({item.get('net_spread_pct', 0):.3f}٪)\n"
        f"تأیید اسکن دوم: تغییر خرید {item.get('confirmation_buy_move_pct', 0):.4f}٪، "
        f"تغییر فروش {item.get('confirmation_sell_move_pct', 0):.4f}٪\n"
        f"پایداری بین اجراهای مستقل: {stable_count}/{MIN_STABLE_SCANS} اسکن\n"
        "فقط شبیه‌سازی؛ معامله واقعی انجام نشده است."
    )


def main():
    print("Independent scheduled Wallex/Nobitex monitor (paper-only).")
    first_result = scan_markets(
        fee_local=FEE_WALLEX, fee_global=FEE_NOBITEX,
        slippage_pct=SLIPPAGE_PCT, transfer_cost_pct=TRANSFER_COST_PCT,
        capital_toman=CAPITAL_TOMAN,
    )
    for error in first_result.get("errors", []):
        print(f"First scan error: {error}")
    first_rows = eligible_opportunities(first_result)
    print(f"First scan eligible routes: {len(first_rows)}")

    if CONFIRM_DELAY_SECONDS > 0:
        time.sleep(CONFIRM_DELAY_SECONDS)
    second_result = scan_markets(
        fee_local=FEE_WALLEX, fee_global=FEE_NOBITEX,
        slippage_pct=SLIPPAGE_PCT, transfer_cost_pct=TRANSFER_COST_PCT,
        capital_toman=CAPITAL_TOMAN,
    )
    for error in second_result.get("errors", []):
        print(f"Confirmation scan error: {error}")
    second_rows = eligible_opportunities(second_result)
    confirmed, rejected = confirm_snapshots(first_rows, second_rows)
    print(f"Confirmed={len(confirmed)}; rejected={len(rejected)}")
    print(f"Confirmation diagnostics: {second_result.get('diagnostics', {})}")

    state = load_state()
    counts = update_stability(confirmed, state, now=time.time())
    stable = [row for row in confirmed if counts.get(route_key(row), 0) >= MIN_STABLE_SCANS]
    stable.sort(key=lambda row: row.get("profit_toman", 0), reverse=True)

    now = time.time()
    new_validations = record_paper_validations(confirmed, state, now)
    alerts = state.setdefault("alerts", {})
    sent = 0
    for item in stable[:5]:
        key = route_key(item)
        if now - float(alerts.get(key, 0) or 0) < COOLDOWN_MINUTES * 60:
            continue
        message = (
            "🔔 فرصت پایدار آربیتراژ برای بررسی\n"
            f"زمان: {datetime.now(TEHRAN).strftime('%Y-%m-%d %H:%M:%S')}\n"
            "حالت: فقط تحلیل و شبیه‌سازی؛ بدون سفارش واقعی\n\n"
            + format_opportunity(1, item, counts.get(key, 0))
            + "\n\n⚠️ این تأیید فقط بر اساس دو snapshot عمومی دفتر سفارش است؛ موجودی، شبکه، انتقال و اجرای واقعی تأیید نشده‌اند."
        )
        try:
            if send_telegram(message):
                alerts[key] = now
                sent += 1
        except (requests.RequestException, RuntimeError) as error:
            print(f"Telegram delivery failed: {type(error).__name__}: {error}")
            break

    today = datetime.now(TEHRAN).strftime("%Y-%m-%d")
    digest_key = f"daily_digest_{today}"
    daily_digest_sent = 0
    if digest_key not in alerts:
        diagnostics = second_result.get("diagnostics", {})
        lines = [
            f"📊 گزارش روزانه پایش آربیتراژ | {today}",
            f"سرمایه شبیه‌سازی: {CAPITAL_TOMAN:,.0f} تومان",
            f"دفتر والکس: {diagnostics.get('wallex_books', '—')} | نوبیتکس: {diagnostics.get('nobitex_books', '—')}",
            f"فرصت‌های تأییدشده با اسکن دوم: {len(confirmed)}",
            f"پایدار در ۵ اجرای مستقل: {len(stable)}",
            f"اعتبارسنجی‌های کاغذی جدید: {len(new_validations)}",
            "فقط تحلیل و شبیه‌سازی؛ بدون سفارش واقعی",
        ]
        try:
            if send_telegram("\n".join(lines)):
                alerts[digest_key] = now
                daily_digest_sent = 1
        except (requests.RequestException, RuntimeError) as error:
            print(f"Daily digest failed: {type(error).__name__}: {error}")

    state["last_run"] = {
        "timestamp": now,
        "first_eligible": len(first_rows),
        "confirmed": len(confirmed),
        "rejected": len(rejected),
        "stable": len(stable),
    }
    save_state(state)
    telegram_messages_sent = sent + daily_digest_sent
    digest_status = "sent" if daily_digest_sent else "already_sent_or_not_due"
    print(
        f"Completed: confirmed={len(confirmed)}, stable={len(stable)}, "
        f"paper validations added={len(new_validations)}, "
        f"Telegram messages sent={telegram_messages_sent} "
        f"(opportunity alerts={sent}, daily digest={digest_status})."
    )


if __name__ == "__main__":
    main()
