"""اجرای محلی یک اسکن؛ فقط داده عمومی، بدون سفارش و بدون تلگرام."""
from datetime import datetime, timezone
from dataclasses import asdict
from config import Settings
from scanner import scan
from db import save_scan


def main():
    settings = Settings.from_env()
    started = datetime.now(timezone.utc).isoformat()
    print("Arbitrage MVP | READ-ONLY | PAPER ONLY")
    print("سفارش، برداشت و انتقال در این برنامه وجود ندارد.")
    result = scan(settings)
    scan_id = save_scan(settings.db_path, started, result, asdict(settings))
    print(f"اسکن #{scan_id} | والکس: {result['wallex_books']} | نوبیتکس: {result['nobitex_books']} | مشترک: {result['common_symbols']}")
    print(f"قابل‌قبول: {result['accepted_count']} | ردشده: {result['rejected_count']}")
    for error in result["errors"]:
        print("خطا:", error)
    for row in sorted(result["opportunities"], key=lambda x: x["estimated_net_profit_toman"], reverse=True):
        print(f"{row['symbol']} | خرید {row['buy_exchange']} ← فروش {row['sell_exchange']} | "
              f"سود تخمینی {row['estimated_net_profit_toman']:,.0f} تومان | "
              f"وضعیت: {'قابل بررسی در paper' if row['eligible'] else 'رد: ' + str(row['rejection_reason'])}")
    print(f"تاریخچه در SQLite ذخیره شد: {settings.db_path}")
    print("توجه: حتی وضعیت قابل‌قبول نیز مجوز معامله واقعی نیست.")


if __name__ == "__main__":
    main()
