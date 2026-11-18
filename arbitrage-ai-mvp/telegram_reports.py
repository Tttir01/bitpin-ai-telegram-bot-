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
    rows = sorted(
        opportunities,
        key=lambda item: item.get("profit_toman", 0),
        reverse=True,
    )[:5]
    lines = [
        "📊 گزارش فرصت‌های آربیتراژ AI",
        f"اسکن شماره: {scan_number}",
        "وضعیت: فقط تحلیل و شبیه‌سازی؛ بدون سفارش واقعی",
        f"دفتر والکس: {diagnostics.get('wallex_books', '—')} | نوبیتکس: {diagnostics.get('nobitex_books', '—')}",
        f"جفت‌ارز مشترک: {diagnostics.get('common_symbols', '—')}",
        f"فرصت‌های واجد شرایط: {len(opportunities)}",
        "",
    ]
    if rows:
        lines.append("رتبه‌بندی بر اساس سود خالص تخمینی:")
        for index, item in enumerate(rows, start=1):
            key = "|".join((
                str(item.get("symbol", "")),
                str(item.get("buy_exchange", "")),
                str(item.get("sell_exchange", "")),
            ))
            stable = stability_counts.get(key, 0)
            lines.extend([
                "",
                f"{index}) {item.get('symbol', '—')}",
                f"مسیر: خرید از {item.get('buy_exchange', '—')} ← فروش در {item.get('sell_exchange', '—')}",
                f"قیمت میانگین خرید: {item.get('buy_vwap', item.get('buy_ask', 0)):,.8g} تومان",
                f"قیمت میانگین فروش: {item.get('sell_vwap', item.get('sell_bid', 0)):,.8g} تومان",
                f"اختلاف قیمت اولیه: {item.get('spread_pct', 0):.3f}٪",
                f"سرمایه درگیر: {item.get('used_capital_toman', 0):,.0f} تومان",
                f"سود ناخالص: {item.get('gross_profit_toman', 0):,.0f} تومان",
                f"کارمزد خرید/فروش: {item.get('buy_fee_toman', 0):,.0f} / {item.get('sell_fee_toman', 0):,.0f} تومان",
                f"لغزش خرید/فروش: {item.get('buy_slippage_toman', 0):,.0f} / {item.get('sell_slippage_toman', 0):,.0f} تومان",
                f"انتقال و سایر هزینه‌ها: {item.get('transfer_cost_toman', 0):,.0f} تومان",
                f"کل هزینه‌ها: {item.get('total_costs_toman', 0):,.0f} تومان",
                f"سود خالص تخمینی: {item.get('profit_toman', 0):,.0f} تومان ({item.get('net_spread_pct', 0):.3f}٪)",
                f"پایداری: {stable} اسکن | پوشش حجم: {item.get('depth_coverage_pct', '—')}٪",
                f"اعتبارسنجی بازار: {item.get('validation_status', '—')}",
                f"هویت دارایی: {item.get('asset_identity_status', 'تأییدنشده')}",
                f"شبکه انتقال: {item.get('network_status', 'نامشخص')}",
                f"واریز/برداشت: {item.get('deposit_withdraw_status', 'نامشخص')}",
                "آمادگی اجرای واقعی: خیر",
            ])
    else:
        lines.append("در این اسکن فرصت واجد شرایطی پیدا نشد.")
    if errors:
        lines.extend(["", "خطاهای دریافت داده:"])
        lines.extend(f"• {str(error)[:180]}" for error in errors[:2])
    lines.extend([
        "",
        "⚠️ همه ارقام برآوردی‌اند؛ هویت دارایی، شبکه، واریز/برداشت و موجودی حساب تأیید نشده‌اند.",
        "این پیام توصیه خرید/فروش نیست و هیچ سفارش یا انتقالی انجام نشده است.",
    ])
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
