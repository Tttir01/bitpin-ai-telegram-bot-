"""آزمایش اتصال read-only به جریان عمق والکس."""
import argparse
import sys
from wallex_stream import collect_wallex_stream


def main():
    parser = argparse.ArgumentParser(description="Wallex Socket.IO read-only diagnostic")
    parser.add_argument("--wait", type=int, default=8, help="زمان جمع‌آوری snapshot بر حسب ثانیه (1..30)")
    args = parser.parse_args()
    try:
        result = collect_wallex_stream(args.wait)
    except Exception as exc:
        print(f"اتصال زنده والکس ناموفق بود: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("این خطا به معنی نبود فرصت نیست؛ داده زنده دریافت نشده است.")
        return 2
    print("Wallex Socket.IO | READ ONLY | DIAGNOSTIC ONLY")
    print(f"بازارهای بررسی‌شده: {result['markets_requested']}")
    print(f"دفترهای کامل دریافت‌شده: {result['books_received']}")
    for symbol, book in sorted(result["books"].items()):
        print(f"{symbol}: asks={len(book['asks'])}, bids={len(book['bids'])}, "
              f"received_at_local={book['received_at']:.3f}, exchange_timestamp=None")
    print("هشدار:", result["warning"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
