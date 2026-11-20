"""تشخیص تغییر snapshotهای REST والکس؛ فقط مشاهده محلی، نه زمان بازار یا سیگنال."""
import argparse
import time
from scanner import fetch_wallex


def book_signature(book, levels=5):
    asks = tuple((round(p, 12), round(q, 12)) for p, q in book.get("asks", [])[:levels])
    bids = tuple((round(p, 12), round(q, 12)) for p, q in book.get("bids", [])[:levels])
    return asks, bids


def compare_snapshots(snapshots):
    """snapshots: iterable از دیکشنری بازارها که fetch_wallex برمی‌گرداند."""
    snapshots = list(snapshots)
    if len(snapshots) < 2:
        raise ValueError("برای مقایسه حداقل دو snapshot لازم است.")
    symbols = sorted(set.intersection(*(set(s) for s in snapshots))) if snapshots else []
    results = {}
    for symbol in symbols:
        signatures = [book_signature(s[symbol]) for s in snapshots]
        results[symbol] = {
            "observations": len(signatures),
            "changed_between_observations": sum(
                signatures[i] != signatures[i - 1] for i in range(1, len(signatures))
            ),
            "unchanged_between_observations": sum(
                signatures[i] == signatures[i - 1] for i in range(1, len(signatures))
            ),
            "timestamp_quality": "local_observation_only",
            "exchange_timestamp_available": all(
                s[symbol].get("exchange_timestamp") is not None for s in snapshots
            ),
        }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()
    if args.samples < 2 or args.samples > 20 or args.interval < 0.5 or args.interval > 60:
        parser.error("--samples باید 2 تا 20 و --interval باید 0.5 تا 60 باشد.")
    snapshots, elapsed = [], []
    for index in range(args.samples):
        started = time.monotonic()
        books = fetch_wallex()
        snapshots.append(books)
        elapsed.append(time.monotonic() - started)
        print(f"نمونه {index + 1}: {len(books)} دفتر؛ زمان دریافت محلی {elapsed[-1]:.3f} ثانیه")
        if index + 1 < args.samples:
            time.sleep(args.interval)
    report = compare_snapshots(snapshots)
    changed = sum(v["changed_between_observations"] > 0 for v in report.values())
    unchanged = sum(v["unchanged_between_observations"] == args.samples - 1 for v in report.values())
    exchange_ts = sum(v["exchange_timestamp_available"] for v in report.values())
    print("\n--- خلاصه تشخیصی ---")
    print(f"بازارهای مشترک در همه نمونه‌ها: {len(report)}")
    print(f"بازارهای دارای تغییر در عمق ۵ سطح برتر: {changed}")
    print(f"بازارهای بدون تغییر در تمام فاصله‌ها: {unchanged}")
    print(f"بازارهای دارای timestamp صرافی در همه نمونه‌ها: {exchange_ts}")
    print("کیفیت زمان مشاهده: فقط زمان محلی دریافت؛ نه timestamp سمت صرافی")
    print("این گزارش سیگنال آربیتراژ تولید نمی‌کند و به اسکنر سود متصل نیست.")


if __name__ == "__main__":
    main()
