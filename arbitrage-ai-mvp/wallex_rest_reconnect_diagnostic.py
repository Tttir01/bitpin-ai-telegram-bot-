"""Read-only REST/WS convergence diagnostic around an intentional Wallex disconnect."""
import json
import time

from wallex_centrifugo_diagnostic import URL, CHANNELS, inspect_frame
from wallex_depth_validator import _rest_snapshot


def _valid_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return False
    sides = snapshot.get("sides", {})
    return all(
        isinstance(sides.get(side), dict)
        and sides[side].get("price") is not None
        and sides[side].get("quantity") is not None
        and int(sides[side].get("levels") or 0) > 0
        for side in ("bid", "ask")
    )


def _pct_diff(left, right):
    try:
        left, right = float(left), float(right)
        if left <= 0 or right <= 0:
            return None
        return abs(left / right - 1.0) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _compare_side(ws_event, rest_side):
    if not ws_event or not rest_side:
        return {"status": "failed", "reason": "missing_side"}
    price_diff = _pct_diff(ws_event.get("price"), rest_side.get("price"))
    qty_diff = _pct_diff(ws_event.get("quantity"), rest_side.get("quantity"))
    if price_diff is None or qty_diff is None:
        return {"status": "failed", "reason": "invalid_top_level"}
    return {
        "status": "candidate" if price_diff <= 0.10 and qty_diff <= 20.0 else "failed",
        "price_diff_pct": round(price_diff, 5),
        "quantity_diff_pct": round(qty_diff, 2),
        "price_tolerance_pct": 0.10,
        "quantity_tolerance_pct": 20.0,
    }


def _connect_and_subscribe(websocket):
    ws = websocket.create_connection(URL, timeout=8, enable_multithread=True)
    ws.settimeout(1)
    ws.send(json.dumps({"id": 1, "connect": {}}))
    connected = False
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not connected:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
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
        raise TimeoutError("Centrifugo handshake timeout")
    for idx, channel in enumerate(CHANNELS, start=2):
        ws.send(json.dumps({"id": idx, "subscribe": {"channel": channel}}))
    ack_ids = set()
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline and len(ack_ids) < 2:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        for line in raw.splitlines():
            try:
                frame = inspect_frame(json.loads(line))
            except (ValueError, TypeError):
                continue
            if frame["kind"] == "ping":
                ws.send("{}")
            elif frame["kind"] == "subscribe_ack":
                ack_ids.add(frame.get("id"))
            elif frame["kind"] == "error":
                raise RuntimeError(frame["error"])
    if len(ack_ids) != 2:
        ws.close()
        raise RuntimeError("Both depth subscriptions were not acknowledged")
    return ws


def _collect_first_depth(ws, wait_seconds):
    events = {"bid": [], "ask": []}
    started = time.monotonic()
    deadline = started + wait_seconds
    while time.monotonic() < deadline and not all(events.values()):
        try:
            raw = ws.recv()
        except Exception as exc:
            if exc.__class__.__name__ == "WebSocketTimeoutException":
                continue
            raise
        for line in raw.splitlines():
            try:
                frame = inspect_frame(json.loads(line))
            except (ValueError, TypeError):
                continue
            if frame["kind"] == "ping":
                ws.send("{}")
            elif frame["kind"] == "error":
                raise RuntimeError(frame["error"])
            elif frame["kind"] == "publication" and frame.get("side") in events:
                side = frame["side"]
                if frame.get("levels", 0) > 0 and frame.get("top_price") and frame.get("top_quantity"):
                    events[side].append({
                        "received_after_reconnect_ms": round((time.monotonic() - started) * 1000),
                        "levels": int(frame["levels"]),
                        "price": frame["top_price"],
                        "quantity": frame["top_quantity"],
                        "metadata_fields": frame.get("timestamp_fields", []),
                    })
    return events


def run_rest_reconnect_convergence(gap_seconds=4, wait_seconds=10):
    if not 2 <= int(gap_seconds) <= 10:
        raise ValueError("gap_seconds must be between 2 and 10")
    if not 3 <= int(wait_seconds) <= 20:
        raise ValueError("wait_seconds must be between 3 and 20")
    result = {
        "status": "failed",
        "gap_seconds": int(gap_seconds),
        "pre_disconnect_rest": None,
        "post_disconnect_rest": None,
        "after_reconnect_ws": {},
        "post_rest_ws_comparison": {},
        "reconnect_delay_ms": None,
        "gap_recovery_verified": False,
        "sequence_order_verified": False,
        "scanner_feed_enabled": False,
        "execution_allowed": False,
    }
    first = second = None
    try:
        import websocket
        result["pre_disconnect_rest"] = _rest_snapshot()
        if not _valid_snapshot(result["pre_disconnect_rest"]):
            raise RuntimeError("Pre-disconnect REST snapshot is incomplete")
        first = _connect_and_subscribe(websocket)
        before = _collect_first_depth(first, 3)
        if not all(before[side] for side in ("bid", "ask")):
            raise RuntimeError("No valid depth publication on both sides before disconnect")
        first.close()
        first = None
        disconnected_at = time.monotonic()
        time.sleep(int(gap_seconds))
        result["post_disconnect_rest"] = _rest_snapshot()
        if not _valid_snapshot(result["post_disconnect_rest"]):
            raise RuntimeError("Post-gap REST snapshot is incomplete")
        second = _connect_and_subscribe(websocket)
        result["reconnect_delay_ms"] = round((time.monotonic() - disconnected_at) * 1000)
        events = _collect_first_depth(second, int(wait_seconds))
        result["after_reconnect_ws"] = {
            side: (events[side][0] if events[side] else None) for side in ("bid", "ask")
        }
        rest_sides = result["post_disconnect_rest"]["sides"]
        result["post_rest_ws_comparison"] = {
            side: _compare_side(result["after_reconnect_ws"].get(side), rest_sides.get(side))
            for side in ("bid", "ask")
        }
        result["status"] = (
            "candidate" if all(
                result["post_rest_ws_comparison"][side]["status"] == "candidate"
                for side in ("bid", "ask")
            ) else "failed"
        )
        result["interpretation"] = (
            "candidate فقط یعنی اولین پیام‌های معتبر پس از اتصال مجدد، در محدوده خطای تعیین‌شده "
            "به بهترین قیمت و حجم REST پس از وقفه نزدیک بوده‌اند. این آزمون replay پیام‌های ازدست‌رفته، "
            "ترتیب کامل رویدادها یا snapshot بودن publicationها را اثبات نمی‌کند."
        )
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        result["interpretation"] = "به‌دلیل خطا یا داده ناکافی، همگرایی تأیید نشد؛ نتیجه باید failed تلقی شود."
        return result
    finally:
        for connection in (first, second):
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
