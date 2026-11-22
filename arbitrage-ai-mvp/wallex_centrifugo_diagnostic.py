"""Read-only Centrifugo connectivity diagnostic for the Streamlit dashboard.

This probe never supplies data to the arbitrage scanner and never authorizes
signals. Local receive time is not an exchange timestamp.
"""
import json
import time

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
        data = (push.get("pub") or {}).get("data")
        if channel in CHANNELS and isinstance(data, (dict, list)):
            keys = []
            if isinstance(data, dict):
                keys = [key for key in data if key in TIMESTAMP_KEYS]
            elif data and isinstance(data[0], dict):
                keys = [key for key in data[0] if key in TIMESTAMP_KEYS]
            return {
                "kind": "publication",
                "channel": channel,
                "levels": len(data),
                "timestamp_fields": keys,
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
            for line in raw.split("\\n"):
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
            for line in raw.split("\\n"):
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
