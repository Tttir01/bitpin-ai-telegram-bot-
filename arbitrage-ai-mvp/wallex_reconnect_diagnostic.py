"""Deliberate disconnect/reconnect probe for public Wallex depth channels.

Read-only diagnostic only. A post-reconnect publication does not prove gap recovery.
"""
import json
import time

from wallex_centrifugo_diagnostic import URL, CHANNELS, inspect_frame


def _open_and_subscribe(websocket_module, phase, wait_seconds):
    ws = websocket_module.create_connection(URL, timeout=8, enable_multithread=True)
    ws.settimeout(1)
    ws.send(json.dumps({"id": 1, "connect": {}}))
    connected = False
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not connected:
        try:
            raw = ws.recv()
        except websocket_module.WebSocketTimeoutException:
            continue
        for line in raw.splitlines():
            try:
                frame = inspect_frame(json.loads(line))
            except (ValueError, TypeError):
                continue
            if frame["kind"] == "ping":
                ws.send("{}")
            elif frame["kind"] == "connect_ack":
                connected = True
            elif frame["kind"] == "error":
                raise RuntimeError(frame["error"])
    if not connected:
        ws.close()
        raise TimeoutError(f"{phase}: connect handshake timeout")

    for idx, channel in enumerate(CHANNELS, start=2):
        ws.send(json.dumps({"id": idx, "subscribe": {"channel": channel}}))
    ack_ids, counts, received = set(), {"bid": 0, "ask": 0}, set()
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        try:
            raw = ws.recv()
        except websocket_module.WebSocketTimeoutException:
            continue
        for line in raw.splitlines():
            try:
                frame = inspect_frame(json.loads(line))
            except (ValueError, TypeError):
                continue
            if frame["kind"] == "ping":
                ws.send("{}")
            elif frame["kind"] == "error":
                raise RuntimeError(frame["error"])
            elif frame["kind"] == "subscribe_ack":
                ack_ids.add(frame.get("id"))
            elif frame["kind"] == "publication":
                side = frame.get("side")
                if side in counts and int(frame.get("levels") or 0) > 0:
                    counts[side] += 1
                    received.add(frame.get("channel"))
    return ws, {
        "connected": connected,
        "subscribe_acks": len(ack_ids),
        "publication_counts": counts,
        "channels_with_valid_depth": sorted(received),
        "both_sides_received": all(counts[s] > 0 for s in ("bid", "ask")),
    }


def _phase_ok(data):
    return bool(
        data.get("connected")
        and data.get("subscribe_acks") == 2
        and data.get("both_sides_received")
        and all(int(data.get("publication_counts", {}).get(side, 0)) > 0 for side in ("bid", "ask"))
    )


def run_reconnect_probe(wait_seconds=8):
    """Observe, deliberately close, reconnect, then observe both public depth channels."""
    if not 3 <= int(wait_seconds) <= 20:
        raise ValueError("wait_seconds must be between 3 and 20")
    try:
        import websocket
    except ImportError as exc:
        raise RuntimeError("websocket-client is not installed") from exc

    result = {
        "status": "failed",
        "execution_allowed": False,
        "scanner_feed_enabled": False,
        "gap_recovery_verified": False,
        "sequence_order_verified": False,
    }
    first = second = None
    try:
        first, result["before_disconnect"] = _open_and_subscribe(websocket, "initial", int(wait_seconds))
        first.close()
        first = None
        result["intentional_disconnect_completed"] = True
        second, result["after_reconnect"] = _open_and_subscribe(websocket, "reconnect", int(wait_seconds))
        passed = all(_phase_ok(result[phase]) for phase in ("before_disconnect", "after_reconnect"))
        result["status"] = "candidate" if passed else "failed"
        result["interpretation"] = (
            "candidate فقط یعنی پس از قطع عمدی، اتصال و اشتراک دوباره برقرار شده و از هر دو سمت "
            "پیام دارای عمق دریافت شده است؛ هیچ مدرکی برای بازیابی پیام‌های ازدست‌رفته، ترتیب کامل "
            "یا همگام‌سازی snapshot ارائه نمی‌کند."
        )
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
        return result
    finally:
        for connection in (first, second):
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
