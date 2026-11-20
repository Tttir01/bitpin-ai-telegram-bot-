"""آزمایش اتصال read-only به جریان عمق والکس."""
import argparse
from wallex_stream import collect_wallex_stream


def main():
    parser = argparse.ArgumentParser(description="Wallex Socket.IO read-only diagnostic")
    parser.add_argument("--wait", type=int, default=8, help="زمان جمع‌آوری snapshot بر حسب ثانیه (1..30)")
    args = parser.parse_args()
    result = collect_wallex_stream(args.wait)
    print("Wallex Socket.IO | READ ONLY | DIAGNOSTIC ONLY")
    print(f"بازارهای بررسی‌شده: {result['markets_requested']}")
    print(f"دفترهای کامل دریافت‌شده: {result['books_received']}")
    for symbol, book in sorted(result["books"].items()):
        print(f"{symbol}: asks={len(book['asks'])}, bids={len(book['bids'])}, "
              f"received_at_local={book['received_at']:.3f}, exchange_timestamp=None")
    print("هشدار:", result["warning"])


if __name__ == "__main__":
    main()
