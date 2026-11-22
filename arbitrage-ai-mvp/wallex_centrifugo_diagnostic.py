"""Read-only Centrifugo connectivity diagnostic for the Streamlit dashboard.

This probe never supplies data to the arbitrage scanner and never authorizes
signals. Local receive time is not an exchange timestamp.
"""
import json
import time

import requests

URL = "wss://api.wallex.ir/connection/websocket"
SYMBOL = "USDTTMN"
CHANNELS = (
    f"orderbook:{SYMBOL}@buyDepth",
    f"orderbook:{SYMBOL}@sellDepth",
)
TIMESTAMP_KEYS = {
    "timestamp", "updated_at", "updatedAt", "lastUpdate",
    "time", "offset", "sequence", "sequenceId", "lastUpdateId",
}


def _timestamp_field_names(payload, depth=0):
    """Find timestamp-like field names without treating them as trustworthy."""
    if depth > 8:
        return set()
    found = set()
    if isinstance(payload, dict):
        found.update(key for key in payload if key in TIMESTAMP_KEYS)
        for value in payload.values():
            if isinstance(value, (dict, list)):
                found.update(_timestamp_field_names(value, depth + 1))
    elif isinstance(payload, list):
        for value in payload[:100]:
            if isinstance(value, (dict, list)):
                found.update(_timestamp_field_names(value, depth + 1))
    return found


_SENSITIVE_KEYS = ("token", "secret", "password", "authorization", "cookie", "api_key", "apikey")


def _safe_payload_preview(payload, max_chars=1400):
    """Compact JSON preview for public market-data diagnostics; redact credential-like fields."""
    def clean(value, depth=0):
        if depth > 6:
            return "[max-depth]"
        if isinstance(value, dict):
            output = {}
            for key, child in list(value.items())[:40]:
                key_text = str(key)
                if any(term in key_text.lower() for term in _SENSITIVE_KEYS):
                    output[key_text] = "[REDACTED]"
                else:
                    output[key_text] = clean(child, depth + 1)
            return output
        if isinstance(value, list):
            return [clean(item, depth + 1) for item in value[:30]]
        if isinstance(value, str):
            return value[:300]
        if value is None or isinstance(value, (int, float, bool)):
            return value
        return str(value)[:120]
    try:
        rendered = json.dumps(clean(payload), ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        rendered = repr(payload)
    return rendered[:max_chars] + ("…[truncated]" if len(rendered) > max_chars else "")

def inspect_frame(message):
    """Return a compact classification for one decoded Centrifugo frame."""
    if not isinstance(message, dict):
        return {"kind": "ignored"}
    if message == {}:
        return {"kind": "ping"}
    if "error" in message:
        return {"kind": "error", "error": str(message.get("error"))[:180]}
    if "id" in message and "connect" in message:
        return {"kind": "connect_ack"}
    if "id" in message and "subscribe" in message:
        return {"kind": "subscribe_ack", "id": message.get("id")}
    push = message.get("push")
    if isinstance(push, dict):
        channel = push.get("channel")
        publication = push.get("pub")
        data = publication.get("data") if isinstance(publication, dict) else None
        if channel in CHANNELS:
            side = "bid" if channel.endswith("@buyDepth") else "ask"
            levels = _extract_side_levels(data, side)
            return {
                "kind": "publication",
                "channel": channel,
                "side": side,
                "payload_preview": _safe_payload_preview(data),
                "levels": len(levels),
                "top_price": levels[0][0] if levels else None,
                "top_quantity": levels[0][1] if levels else None,
                "timestamp_fields": sorted(_timestamp_field_names(data)),
                "payload_shape": (
                    "numeric_keyed_map"
                    if isinstance(data, dict) and data and all(str(key).isdigit() for key in data)
                    else "message_envelope" if isinstance(data, dict) and isinstance(data.get("message"), list)
                    else "list" if isinstance(data, list) else "object"
                ),
            }
    return {"kind": "ignored"}


def run_diagnostic(wait_seconds=10):
    """Connect, subscribe to two public depth channels, and observe publications."""
    if not 2 <= int(wait_seconds) <= 20:
        raise ValueError("wait_seconds must be between 2 and 20")
    try:
        import websocket
    except ImportError as exc:
        raise RuntimeError("websocket-client is not installed") from exc

    ws = websocket.create_connection(URL, timeout=8, enable_multithread=True)
    result = {
        "connected": False,
        "subscribe_acks": 0,
        "received_channels": [],
        "publications": 0,
        "timestamp_fields": [],
        "execution_allowed": False,
    }
    try:
        ws.settimeout(1)
        ws.send(json.dumps({"id": 1, "connect": {}}))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not result["connected"]:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            for line in raw.splitlines():
                if not line:
                    continue
                try:
                    frame = inspect_frame(json.loads(line))
                except (ValueError, TypeError):
                    continue
                if frame["kind"] == "ping":
                    ws.send("{}")
                elif frame["kind"] == "connect_ack":
                    result["connected"] = True
                elif frame["kind"] == "error":
                    result["error"] = frame["error"]
                    return result
        if not result["connected"]:
            result["error"] = "مهلت پاسخ handshake تمام شد"
            return result

        for index, channel in enumerate(CHANNELS, start=2):
            ws.send(json.dumps({"id": index, "subscribe": {"channel": channel}}))

        subscribed_ids = set()
        received = set()
        deadline = time.monotonic() + int(wait_seconds)
        while time.monotonic() < deadline:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            for line in raw.splitlines():
                if not line:
                    continue
                try:
                    frame = inspect_frame(json.loads(line))
                except (ValueError, TypeError):
                    continue
                if frame["kind"] == "ping":
                    ws.send("{}")
                elif frame["kind"] == "error":
                    result.setdefault("errors", []).append(frame["error"])
                elif frame["kind"] == "subscribe_ack":
                    subscribed_ids.add(frame.get("id"))
                elif frame["kind"] == "publication":
                    result["publications"] += 1
                    received.add(frame["channel"])
                    result["timestamp_fields"].extend(frame["timestamp_fields"])
        result["subscribe_acks"] = len(subscribed_ids)
        result["received_channels"] = sorted(received)
        result["both_depth_sides_received"] = set(CHANNELS).issubset(received)
        result["timestamp_fields"] = sorted(set(result["timestamp_fields"]))
        result["warning"] = (
            "دریافت پیام فقط اتصال جریان را اثبات می‌کند؛ timestamp سمت صرافی، "
            "ترتیب کامل snapshotها و همگام‌سازی با REST را اثبات نمی‌کند."
        )
        return result
    finally:
        ws.close()


def _positive_number(value):
    try:
        number = float(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _parse_level_list(value, side):
    if not isinstance(value, list):
        return []
    levels = []
    for item in value:
        if isinstance(item, dict):
            price = _positive_number(item.get("price"))
            quantity = _positive_number(item.get("quantity", item.get("qty", item.get("amount"))))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            price = _positive_number(item[0])
            quantity = _positive_number(item[1])
        else:
            continue
        if price is not None and quantity is not None:
            levels.append((price, quantity))
    return sorted(levels, key=lambda row: row[0], reverse=(side == "bid"))


def _parse_numeric_level_mapping(value, side):
    """Parse Wallex depth maps whose numeric keys contain {price, quantity} rows."""
    if not isinstance(value, dict) or not value:
        return []
    if not all(str(key).isdigit() for key in value):
        return []
    ordered = [value[key] for key in sorted(value, key=lambda item: int(item))]
    return _parse_level_list(ordered, side)


def _extract_side_levels(payload, side, depth=0):
    """Parse common REST/Centrifugo envelopes, including numeric-keyed depth maps."""
    if depth > 8:
        return []
    if isinstance(payload, dict):
        names = ("bids", "bid", "buy", "buyDepth") if side == "bid" else ("asks", "ask", "sell", "sellDepth")
        for name in names:
            parsed = _parse_level_list(payload.get(name), side)
            if not parsed:
                parsed = _parse_numeric_level_mapping(payload.get(name), side)
            if parsed:
                return parsed

        # Wallex Broadcaster depth payloads may be {"0": {...}, "1": {...}}.
        parsed = _parse_numeric_level_mapping(payload, side)
        if parsed:
            return parsed

        for name in ("result", "data", "message", "book", "orderbook", "depth", "symbols"):
            child = payload.get(name)
            if isinstance(child, (dict, list)):
                parsed = _extract_side_levels(child, side, depth + 1)
                if parsed:
                    return parsed
        price = _positive_number(payload.get("price"))
        quantity = _positive_number(payload.get("quantity", payload.get("qty")))
        if price is not None and quantity is not None:
            return [(price, quantity)]
    elif isinstance(payload, list):
        parsed = _parse_level_list(payload, side)
        if parsed:
            return parsed
        for child in payload[:100]:
            parsed = _extract_side_levels(child, side, depth + 1)
            if parsed:
                return parsed
    return []


def _find_wallex_symbol_book(payload):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise RuntimeError("پاسخ REST دفتر سفارش والکس معتبر نیست.")
    result = payload.get("result") or payload.get("data") or {}
    if isinstance(result, dict) and isinstance(result.get("symbols"), dict):
        result = result["symbols"]
    if not isinstance(result, dict):
        raise RuntimeError("ساختار REST دفتر سفارش والکس قابل شناسایی نیست.")
    for key in ("USDTTMN", "USDT/TMN", "USDTIRT", "USDT/IRT"):
        book = result.get(key)
        if isinstance(book, dict):
            return book
    raise RuntimeError("بازار USDTTMN در پاسخ REST پیدا نشد.")


def run_parity_diagnostic(wait_seconds=10, price_tolerance_pct=0.10):
    """Compare REST top levels with subsequent public Centrifugo publications.

    This is diagnostic only and never updates the scanner or authorizes trading.
    """
    if not 2 <= int(wait_seconds) <= 20:
        raise ValueError("wait_seconds must be between 2 and 20")
    try:
        import websocket
    except ImportError as exc:
        raise RuntimeError("websocket-client is not installed") from exc

    ws = websocket.create_connection(URL, timeout=8, enable_multithread=True)
    result = {
        "connected": False, "subscribe_acks": 0, "publication_count": 0,
        "received_channels": [], "rest": {}, "websocket": {},
        "payload_samples": {"bid": [], "ask": []},
        "comparisons": {}, "execution_allowed": False,
    }
    try:
        ws.settimeout(1)
        ws.send(json.dumps({"id": 1, "connect": {}}))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not result["connected"]:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            for line in raw.splitlines():
                if not line:
                    continue
                try:
                    frame = inspect_frame(json.loads(line))
                except (ValueError, TypeError):
                    continue
                if frame["kind"] == "ping":
                    ws.send("{}")
                elif frame["kind"] == "connect_ack":
                    result["connected"] = True
                elif frame["kind"] == "error":
                    result["error"] = frame["error"]
                    return result
        if not result["connected"]:
            result["error"] = "مهلت handshake تمام شد"
            return result

        for index, channel in enumerate(CHANNELS, start=2):
            ws.send(json.dumps({"id": index, "subscribe": {"channel": channel}}))

        ack_ids = set()
        ack_deadline = time.monotonic() + 6
        while time.monotonic() < ack_deadline and len(ack_ids) < 2:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            for line in raw.splitlines():
                if not line:
                    continue
                try:
                    frame = inspect_frame(json.loads(line))
                except (ValueError, TypeError):
                    continue
                if frame["kind"] == "ping":
                    ws.send("{}")
                elif frame["kind"] == "subscribe_ack":
                    ack_ids.add(frame.get("id"))
                elif frame["kind"] == "error":
                    result.setdefault("errors", []).append(frame["error"])
        result["subscribe_acks"] = len(ack_ids)

        rest_started = time.monotonic()
        response = requests.get(
            "https://api.wallex.ir/v2/depth/all",
            headers={"Accept": "application/json", "User-Agent": "ArbitrageMVP-ReadOnly/1.0"},
            timeout=(5, 12),
        )
        response.raise_for_status()
        rest_book = _find_wallex_symbol_book(response.json())
        rest_levels = {
            "bid": _extract_side_levels(rest_book, "bid"),
            "ask": _extract_side_levels(rest_book, "ask"),
        }
        rest_finished = time.monotonic()
        result["rest_latency_ms"] = round((rest_finished - rest_started) * 1000)
        for side, levels in rest_levels.items():
            if levels:
                result["rest"][side] = {"price": levels[0][0], "quantity": levels[0][1]}

        received = set()
        deadline = time.monotonic() + int(wait_seconds)
        while time.monotonic() < deadline:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            for line in raw.splitlines():
                if not line:
                    continue
                try:
                    frame = inspect_frame(json.loads(line))
                except (ValueError, TypeError):
                    continue
                if frame["kind"] == "ping":
                    ws.send("{}")
                elif frame["kind"] == "error":
                    result.setdefault("errors", []).append(frame["error"])
                elif frame["kind"] == "publication":
                    result["publication_count"] += 1
                    received.add(frame["channel"])
                    side = frame.get("side")
                    if side in ("bid", "ask") and len(result["payload_samples"][side]) < 2:
                        result["payload_samples"][side].append({
                            "levels_extracted": frame.get("levels", 0),
                            "payload_shape": frame.get("payload_shape", "unknown"),
                            "preview": frame.get("payload_preview", ""),
                        })
                    if side in ("bid", "ask") and frame.get("top_price") and frame.get("top_quantity"):
                        result["websocket"][side] = {
                            "price": frame["top_price"], "quantity": frame["top_quantity"]
                        }
        result["received_channels"] = sorted(received)
        for side in ("bid", "ask"):
            rest_top = result["rest"].get(side)
            ws_top = result["websocket"].get(side)
            if not rest_top or not ws_top:
                result["comparisons"][side] = {"status": "not_comparable"}
                continue
            price_diff = abs(ws_top["price"] / rest_top["price"] - 1) * 100
            qty_diff = abs(ws_top["quantity"] / rest_top["quantity"] - 1) * 100
            result["comparisons"][side] = {
                "status": "price_within_tolerance" if price_diff <= price_tolerance_pct else "price_mismatch",
                "price_diff_pct": round(price_diff, 5),
                "quantity_diff_pct": round(qty_diff, 2),
                "tolerance_pct": price_tolerance_pct,
            }
        result["both_sides_compared"] = all(
            result["comparisons"].get(side, {}).get("status") != "not_comparable"
            for side in ("bid", "ask")
        )
        result["warning"] = (
            "این مقایسه فقط بهترین قیمت REST را با اولین سطح قابل‌استخراج از پیام‌های بعد از REST می‌سنجد. "
            "به‌دلیل احتمال delta بودن پیام‌ها، تأخیر شبکه و نبود تضمین snapshot/sequence، "
            "تطبیق قیمت به معنی همگام‌سازی کامل دفتر یا مجوز معامله نیست."
        )
        return result
    finally:
        ws.close()
