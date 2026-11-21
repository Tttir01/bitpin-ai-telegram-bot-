"""Read-only diagnostic: inspect Wallex REST depth timestamp metadata.

The HTTP Date header is server response time, NOT an order-book update timestamp.
This probe never feeds the scanner or changes eligibility.
"""
from datetime import datetime, timezone
import requests

BASE = "https://api.wallex.ir"
HEADERS = {"Accept": "application/json", "User-Agent": "ArbitrageMVP-ReadOnly/1.0"}
TIMESTAMP_KEYS = {"timestamp", "updated_at", "updatedAt", "lastUpdate", "time", "sequence", "sequenceId", "lastUpdateId"}


def inspect_depth(payload):
    root = payload.get("result") or payload.get("data") or {}
    if not isinstance(root, dict):
        return [], []
    if "ask" in root or "asks" in root or "bid" in root or "bids" in root:
        samples = [("single-market", root)]
    else:
        samples = [(str(k), v) for k, v in list(root.items())[:3] if isinstance(v, dict)]
    found = []
    level_keys = []
    for market, book in samples:
        found.extend(f"{market}.{key}" for key in book if key in TIMESTAMP_KEYS)
        for side in ("ask", "asks", "bid", "bids"):
            levels = book.get(side)
            if isinstance(levels, list) and levels and isinstance(levels[0], dict):
                level_keys.extend(f"{market}.{side}[0].{key}" for key in levels[0] if key in TIMESTAMP_KEYS)
    return found, level_keys


def probe(label, url, params=None):
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=(5, 15))
        print(f"[{label}] HTTP {response.status_code}")
        date_header = response.headers.get("Date")
        print(f"[{label}] HTTP Date header (response time only): {date_header or 'missing'}")
        if date_header:
            try:
                server_dt = datetime.strptime(date_header, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
                skew = (datetime.now(timezone.utc) - server_dt).total_seconds()
                print(f"[{label}] local_minus_server_date_seconds={skew:.1f} (diagnostic only)")
            except ValueError:
                pass
        response.raise_for_status()
        payload = response.json()
        found, level_keys = inspect_depth(payload)
        print(f"[{label}] payload_top_keys={list(payload)[:12] if isinstance(payload, dict) else type(payload).__name__}")
        print(f"[{label}] timestamp_like_book_fields={found or 'none in sampled book objects'}")
        print(f"[{label}] timestamp_like_level_fields={level_keys or 'none in sampled levels'}")
        print(f"[{label}] NOTE: HTTP Date is not accepted as order-book timestamp.")
    except Exception as exc:
        print(f"[{label}] {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    probe("v1 single-market depth", f"{BASE}/v1/depth", {"symbol": "USDTTMN"})
    probe("v2 all-market depth", f"{BASE}/v2/depth/all")
