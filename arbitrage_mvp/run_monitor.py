"""پایش زمان‌بندی‌شده MVP؛ فقط داده عمومی و گزارش تلگرام، بدون سفارش.

Push-triggered runs of this entrypoint are read-only smoke checks.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import os
import sys
import requests

from config import Settings
from scanner import scan
from db import save_scan


def build_report(scan_id: int, result: dict) -> str:
    lines = [
        "📊 گزارش پایش آربیتراژ والکس / نوبیتکس",
        f"اسکن: #{scan_id}",
        "حالت: فقط‌خواندنی و شبیه‌سازی؛ سفارش واقعی غیرفعال",
        f"دفترهای والکس: {result.get('wallex_books', 0)}",
        f"دفترهای نوبیتکس: {result.get('nobitex_books', 0)}",
        f"بازارهای مشترک: {result.get('common_symbols', 0)}",
        f"سیگنال واجد شرایط: {result.get('accepted_count', 0)}",
        f"فرصت ردشده: {result.get('rejected_count', 0)}",
    ]
    opportunities = result.get("opportunities", [])
    missing_time = sum(1 for item in opportunities if not item.get("freshness_verified"))
    if missing_time:
        lines.append(
            f"⛔ {missing_time} مسیر به‌علت نبود timestamp معتبر سمت صرافی رد شد."
        )
    if result.get("errors"):
        lines.append("خطاهای دریافت داده:")
        lines.extend(f"• {str(error)[:220]}" for error in result["errors"][:3])
    accepted = [
        item for item in opportunities
        if item.get("eligible") is True
    ]
    if accepted:
        lines.append("فرصت‌های قابل بررسی در paper:")
        for item in sorted(
            accepted, key=lambda row: row.get("estimated_net_profit_toman", 0),
            reverse=True
        )[:3]:
            lines.append(
                f"• {item['symbol']}: خرید {item['buy_exchange']} / "
                f"فروش {item['sell_exchange']} | سود تخمینی "
                f"{item['estimated_net_profit_toman']:,.0f} تومان"
            )
    else:
        lines.append("در این اسکن هیچ سیگنال قابل‌تأییدی برای معامله وجود ندارد.")
    run_url = os.getenv("GITHUB_SERVER_URL", "").rstrip("/") + "/" + os.getenv("GITHUB_REPOSITORY", "") + "/actions/runs/" + os.getenv("GITHUB_RUN_ID", "")
    if os.getenv("GITHUB_RUN_ID"):
        lines.append(f"گزارش اجرا: {run_url}")
    lines.append("هیچ سفارش، برداشت یا انتقالی انجام نشده است.")
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
    payload = response.json()
    if payload.get("ok") is not True:
        raise RuntimeError("Telegram API did not confirm message delivery.")
    print("Telegram diagnostic report delivered.")


def main() -> int:
    settings = Settings.from_env()
    started = datetime.now(timezone.utc).isoformat()
    result = scan(settings)
    scan_id = save_scan(settings.db_path, started, result, asdict(settings))
    message = build_report(scan_id, result)
    print(message)
    send_telegram(message)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Monitor failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
