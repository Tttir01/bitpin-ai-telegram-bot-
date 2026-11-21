"""Probe the documented Wallex Hector public markets endpoint (read-only).

This endpoint is documented for market metadata, not as an order-book source.
No market/trade timestamp is ever treated as an order-book timestamp.
"""
import json
import requests

URL = "https://api.wallex.ir/hector/web/v1/markets"
HEADERS = {"Accept": "application/json", "User-Agent": "ArbitrageMVP-ReadOnly/1.0"}


def walk(value, path="$"):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if any(token in key.lower() for token in ("time", "date", "update", "timestamp")):
                print(f"TIME_FIELD {child_path}={json.dumps(child, ensure_ascii=False)[:160]}")
            walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value[:3]):
            walk(child, f"{path}[{index}]")


def main():
    try:
        response = requests.get(URL, headers=HEADERS, timeout=(5, 15))
        print(f"GET {URL} -> HTTP {response.status_code}")
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"HECTOR_MARKETS_PROBE_FAILED: {type(exc).__name__}: {exc}")
        return 2

    if not isinstance(payload, dict):
        print(f"Unexpected response type: {type(payload).__name__}")
        return 2

    print("top-level-keys=" + ",".join(map(str, list(payload.keys())[:40])))
    result = payload.get("result")
    if not isinstance(result, dict):
        print("result is not an object")
        return 2
    print("result-keys=" + ",".join(map(str, list(result.keys())[:40])))

    markets = result.get("markets")
    if isinstance(markets, dict):
        print(f"markets-type=dict count={len(markets)}")
        if markets:
            symbol, sample = next(iter(markets.items()))
            print(f"sample-market={symbol}")
            if isinstance(sample, dict):
                print("sample-market-fields=" + ",".join(map(str, list(sample.keys())[:80])))
                for key, value in sample.items():
                    if isinstance(value, dict):
                        print(f"sample-nested-{key}-fields=" + ",".join(map(str, list(value.keys())[:50])))
    elif isinstance(markets, list):
        print(f"markets-type=list count={len(markets)}")
        if markets and isinstance(markets[0], dict):
            print("sample-market-fields=" + ",".join(map(str, list(markets[0].keys())[:80])))
    else:
        print(f"markets-type={type(markets).__name__}")

    walk(result)
    print("NOTE: metadata/trade timestamps are not order-book timestamps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
