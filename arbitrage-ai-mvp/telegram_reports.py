import os
import requests


def telegram_configured():
    return bool(
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        and os.getenv("TELEGRAM_CHAT_ID", "").strip()
    )


def send_message(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False, "تنظیمات تلگرام در Render کامل نیست."
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            return False, str(payload.get("description", "Telegram API error"))
        return True, "پیام ارسال شد."
    except requests.RequestException as exc:
        return False, f"Telegram connection error: {type(exc).__name__}"


def send_scan_report(opportunities, stability_counts, scan_number, diagnostics, errors=None):
    rows = sorted(opportunities, key=lambda item: item.get("profit_toman", 0), reverse=True)[:5]
    lines = [
        "📊 گزارش آربیتراژ AI",
        f"اسکن شماره: {scan_number}",
        "وضعیت: فقط تحلیل و شبیه‌سازی؛ بدون سفارش واقعی",
        f"دفتر والکس: {diagnostics.get('wallex_books', '—')} | نوبیتکس: {diagnostics.get('nobitex_books', '—')}",
        f"جفت‌ارز مشترک: {diagnostics.get('common_symbols', '—')}",
        f"فرصت‌های واجد شرایط: {len(opportunities)}",
        "",
    ]
    if rows:
        lines.append("بهترین فرصت‌ها:")
        for item in rows:
            key = "|".join((
                str(item.get("symbol", "")),
                str(item.get("buy_exchange", "")),
                str(item.get("sell_exchange", "")),
            ))
            stable = stability_counts.get(key, 0)
            lines.append(
                f"• {item.get('symbol', '—')}: خرید {item.get('buy_exchange', '—')}، "
                f"فروش {item.get('sell_exchange', '—')} | "
                f"سود تخمینی {item.get('profit_toman', 0):,.0f} تومان "
                f"({item.get('net_spread_pct', 0):.2f}٪) | پایداری {stable} اسکن"
            )
    else:
        lines.append("در این اسکن فرصت واجد شرایطی پیدا نشد.")
    if errors:
        lines.extend(["", "خطاهای دریافت داده:"])
        lines.extend(f"• {str(error)[:180]}" for error in errors[:2])
    lines.extend(["", "⚠️ سودها فرضی‌اند؛ موجودی، انتقال و اجرای واقعی تأیید نشده‌اند."])
    return send_message("\n".join(lines))


def send_paper_trade_report(trade):
    message = (
        "🧪 ثبت معامله کاغذی جدید\n"
        f"جفت‌ارز: {trade.get('جفت‌ارز', '—')}\n"
        f"خرید: {trade.get('صرافی خرید', '—')} | فروش: {trade.get('صرافی فروش', '—')}\n"
        f"سرمایه شبیه‌سازی: {trade.get('سرمایه مصرفی (تومان)', 0):,} تومان\n"
        f"سود/زیان تخمینی: {trade.get('سود/زیان خالص (تومان)', 0):,} تومان\n"
        f"بازده تخمینی: {trade.get('بازده خالص (%)', 0):.2f}٪\n"
        f"زمان: {trade.get('زمان', '—')}\n"
        "⚠️ این معامله واقعی نیست و هیچ سفارش یا انتقالی انجام نشده است."
    )
    return send_message(message)
