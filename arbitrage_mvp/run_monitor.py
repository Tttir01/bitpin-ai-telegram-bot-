"""پایش زمان‌بندی‌شده MVP؛ فقط داده عمومی و گزارش تلگرام، بدون سفارش."""
from dataclasses import asdict
from datetime import datetime, timezone
import os
import sys
import requests

from config import Settings
from scanner import scan
from potential_scanner import scan_potential
from db import save_scan


def build_report(scan_id: int, result: dict, potential: dict | None = None) -> str:
    lines = [
        "📊 گزارش پایش آربیتراژ والکس / نوبیتکس",
        f"اسکن: #{scan_id}",
        "حالت: فقط‌خواندنی؛ سفارش واقعی، برداشت و انتقال غیرفعال",
        f"دفترهای والکس: {result.get('wallex_books', 0)}",
        f"دفترهای نوبیتکس: {result.get('nobitex_books', 0)}",
        f"بازارهای مشترک: {result.get('common_symbols', 0)}",
        f"سیگنال تأییدشده: {result.get('accepted_count', 0)}",
        f"مسیر ردشده: {result.get('rejected_count', 0)}",
    ]
    opportunities = result.get("opportunities", [])
    missing_time = sum(1 for item in opportunities if not item.get("freshness_verified"))
    if missing_time:
        lines.append(f"⛔ {missing_time} مسیر به‌علت نبود timestamp معتبر سمت صرافی رد شد.")
    accepted = [
        item for item in opportunities
        if item.get("eligible") is True and item.get("freshness_verified") is True
    ]
    if accepted:
        lines.append("فرصت‌های تأییدشده برای بررسی در paper:")
        for item in sorted(
            accepted, key=lambda row: row.get("estimated_net_profit_toman", 0),
            reverse=True
        )[:3]:
            lines.append(
                f"• {item.get('symbol', 'نامشخص')}: خرید {item.get('buy_exchange', 'نامشخص')} / "
                f"فروش {item.get('sell_exchange', 'نامشخص')} | "
                f"{item.get('estimated_net_profit_toman', 0):,.0f} تومان"
            )
    else:
        lines.append("در این اسکن هیچ سیگنال قابل‌تأییدی برای معامله وجود ندارد.")
    if result.get("errors"):
        lines.append("خطاهای اسکن تأییدی:")
        lines.extend(f"• {str(error)[:180]}" for error in result["errors"][:2])

    # بخش دوم مستقل است و هرگز در شمار سیگنال‌های تأییدشده/واجدشرایط وارد نمی‌شود.
    potential = potential or {}
    candidates = [
        item for item in potential.get("potential_opportunities", [])
        if item.get("status") == "POTENTIAL_ONLY_LOCAL_RECEIVE_TIME"
        and item.get("transport_quality_ok") is True
    ]
    lines.extend([
        "",
        "🔎 پایش فرصت احتمالی (غیرقابل معامله)",
        "مبنای زمان: زمان دریافت محلی کلاینت؛ نه زمان رسمی دفتر سفارش",
        f"اختلاف زمان دریافت دو پاسخ: {potential.get('receive_skew_seconds', 'نامشخص')} ثانیه",
        f"فرصت احتمالی با کنترل کیفیت انتقال: {len(candidates)}",
    ])
    if candidates:
        for item in sorted(
            candidates, key=lambda row: row.get("estimated_net_profit_toman", 0),
            reverse=True
        )[:3]:
            lines.append(
                f"• {item['symbol']}: خرید {item['buy_exchange']} / فروش "
                f"{item['sell_exchange']} | برآورد خام {item['estimated_net_profit_toman']:,.0f} تومان"
            )
    else:
        lines.append("در این نوبت فرصت احتمالی با کیفیت انتقال قابل‌قبول پیدا نشد.")
    if potential.get("errors"):
        lines.append("خطای پایش احتمالی: " + " | ".join(str(x)[:140] for x in potential["errors"][:2]))
    lines.append("⚠️ زمان دریافت محلی تازگی سمت صرافی یا هم‌زمانی واقعی دو دفتر را ثابت نمی‌کند؛ این موارد فقط سرنخ پژوهشی‌اند.")
    lines.append("هیچ سفارش، برداشت یا انتقالی انجام نشده است.")

    if os.getenv("GITHUB_RUN_ID"):
        run_url = (
            os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
            + "/" + os.getenv("GITHUB_REPOSITORY", "")
            + "/actions/runs/" + os.getenv("GITHUB_RUN_ID", "")
        )
        lines.append(f"گزارش اجرا: {run_url}")
    return "\n".join(lines)


def send_telegram(message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram skipped: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID secrets are not configured.")
        return
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
        timeout=(5, 20),
    )
    response.raise_for_status()
    if response.json().get("ok") is not True:
        raise RuntimeError("Telegram API did not confirm message delivery.")
    print("Telegram diagnostic report delivered.")


def main() -> int:
    settings = Settings.from_env()
    started = datetime.now(timezone.utc).isoformat()
    verified_result = scan(settings)  # گیت timestamp سمت صرافی بدون تغییر
    potential_result = scan_potential(settings)  # مسیر جداگانه و صریحاً غیرقابل معامله
    scan_id = save_scan(settings.db_path, started, verified_result, asdict(settings))
    message = build_report(scan_id, verified_result, potential_result)
    print(message)
    send_telegram(message)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Monitor failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
