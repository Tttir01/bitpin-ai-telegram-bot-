"""Probe the documented Wallex Hector public markets endpoint (read-only).

This endpoint is documented for markets metadata, not as an order-book source.
The probe reports structure and timestamp-like field names without treating any
market/trade timestamp as an order-book timestamp.
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
                rendered = json.dumps(child, ensure_ascii=False)[:180]
                print(f"FIELD {child_path} = {rendered}")
            walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value[:3]):
            walk(child, f"{path}[{index}]")


def main():
    try:
        response = requests.get(URL, headers=HEADERS, timeout=(5, 15))
        print(f"GET {URL} -> HTTP {response.status_code}")
        print(f"content-type={response.headers.get('Content-Type', '')}")
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"HECTOR_MARKETS_PROBE_FAILED: {type(exc).__name__}: {exc}")
        return 2

    if not isinstance(payload, (dict, list)):
        print(f"Unexpected response type: {type(payload).__name__}")
        return 2

    print("top-level-type=" + type(payload).__name__)
    if isinstance(payload, dict):
        print("top-level-keys=" + ",".join(map(str, list(payload.keys())[:40])))
    walk(payload)

    # Show a compact sample shape only; never print credentials or full payload.
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, dict):
                print("sample-object-key=" + str(key))
                print("sample-object-fields=" + ",".join(map(str, list(value.keys())[:60])))
                break
            if isinstance(value, list) and value and isinstance(value[0], dict):
                print("sample-list-key=" + str(key))
                print("sample-list-fields=" + ",".join(map(str, list(value[0].keys())[:60])))
                break

    print("NOTE: this documented endpoint is a markets-metadata probe, not proof of order-book timestamps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
