"""Independent, read-only Wallex Centrifugo depth validator.

This module is diagnostic only. It never feeds the scanner or execution pipeline.
A candidate result is NOT proof of snapshot semantics, recovery, or trading safety.
"""
import time
import requests

from wallex_centrifugo_diagnostic import (
    URL, SYMBOL, CHANNELS, inspect_frame, _find_wallex_symbol_book,
    _extract_side_levels,
)

REST_URL = "https://api.wallex.ir/v2/depth/all"


def _rest_snapshot():
    started = time.monotonic()
    response = requests.get(
        REST_URL,
        headers={"Accept": "application/json", "User-Agent": "ArbitrageMVP-ReadOnly/1.0"},
        timeout=(5, 12),
    )
    response.raise_for_status()
    book = _find_wallex_symbol_book(response.json())
    finished = time.monotonic()
    output = {"started_monotonic": started, "finished_monotonic": finished,
              "latency_ms": round((finished - started) * 1000), "sides": {}}
    for side in ("bid", "ask"):
        levels = _extract_side_levels(book, side)
        output["sides"][side] = {
            "levels": len(levels),
            "price": levels[0][0] if levels else None,
            "quantity": levels[0][1] if levels else None,
        }
    return output


def _pct_diff(left, right):
    if left is None or right in (None, 0):
        return None
    return abs(left / right - 1.0) * 100.0


def _side_summary(events, rest_before, rest_after, min_messages):
    if not events:
        return {"sample_count": 0, "status": "failed", "reason": "no_publications"}
    first, last = events[0], events[-1]
    prices = [item["price"] for item in events if item["price"] is not None]
    quantities = [item["quantity"] for item in events if item["quantity"] is not None]
    max_levels = max(item["levels"] for item in events)
    rest_candidates = [
        snap["sides"].get("bid" if events[0]["side"] == "bid" else "ask", {})
        for snap in (rest_before, rest_after) if snap
    ]
    best_price_diff = min(
        (_pct_diff(last["price"], snap.get("price")) for snap in rest_candidates
         if snap.get("price") is not None and last["price"] is not None),
        default=None,
    )
    best_qty_diff = min(
        (_pct_diff(last["quantity"], snap.get("quantity")) for snap in rest_candidates
         if snap.get("quantity") is not None and last["quantity"] is not None),
        default=None,
    )
    status = "candidate" if (
        len(events) >= min_messages and max_levels > 0 and
        best_price_diff is not None and best_price_diff <= 0.10 and
        best_qty_diff is not None and best_qty_diff <= 20.0
    ) else "failed"
    return {
        "sample_count": len(events),
        "first": {k: first[k] for k in ("received_after_start_ms", "levels", "price", "quantity")},
        "last": {k: last[k] for k in ("received_after_start_ms", "levels", "price", "quantity")},
        "max_levels": max_levels,
        "min_levels": min(item["levels"] for item in events),
        "top_price_changes": sum(1 for a, b in zip(prices, prices[1:]) if a != b),
        "top_quantity_changes": sum(1 for a, b in zip(quantities, quantities[1:]) if a != b),
        "rest_best_price_diff_pct": round(best_price_diff, 5) if best_price_diff is not None else None,
        "rest_best_quantity_diff_pct": round(best_qty_diff, 2) if best_qty_diff is not None else None,
        "timestamp_or_sequence_fields_seen": sorted(set(
            key for item in events for key in item["metadata_fields"]
        )),
        "status": status,
    }


def run_depth_validation(wait_seconds=20, min_messages=10):
    """Observe both channels between REST snapshots; all timing is local monotonic time."""
    if not 5 <= int(wait_seconds) <= 60:
        raise ValueError("wait_seconds must be between 5 and 60")
    if not 1 <= int(min_messages) <= 100:
        raise ValueError("min_messages must be between 1 and 100")
    try:
        import json
        import websocket
    except ImportError as exc:
        raise RuntimeError("websocket-client is not installed") from exc

    result = {
        "status": "failed", "connected": False, "subscribe_acks": 0,
        "execution_allowed": False, "scanner_feed_enabled": False,
        "rest_before": None, "rest_after": None, "sides": {},
        "sequence_recovery_verified": False, "snapshot_semantics_verified": False,
        "transport": {"recv_calls": 0, "timeout_returns": 0, "empty_recv_returns": 0,
                      "nonempty_recv_returns": 0, "total_received_chars": 0,
                      "raw_frames": 0, "json_frames": 0, "ping_frames": 0,
                      "ignored_frames": 0, "unknown_push_channels": [],
                      "publication_frames": 0, "zero_level_publications": 0,
                      "frame_previews": []},
    }
    ws = None
    try:
        ws = websocket.create_connection(URL, timeout=8, enable_multithread=True)
        ws.settimeout(1)
        ws.send(json.dumps({"id": 1, "connect": {}}))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not result["connected"]:
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
                    result["connected"] = True
                elif frame["kind"] == "error":
                    raise RuntimeError(frame["error"])
        if not result["connected"]:
            raise RuntimeError("مهلت handshake تمام شد")

        for idx, channel in enumerate(CHANNELS, start=2):
            ws.send(json.dumps({"id": idx, "subscribe": {"channel": channel}}))
        ack_ids = set()
        ack_deadline = time.monotonic() + 6
        while time.monotonic() < ack_deadline and len(ack_ids) < 2:
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
        result["subscribe_acks"] = len(ack_ids)
        if len(ack_ids) != 2:
            raise RuntimeError("اشتراک هر دو کانال تأیید نشد")

        result["rest_before"] = _rest_snapshot()
        started = time.monotonic()
        events = {"bid": [], "ask": []}
        deadline = started + int(wait_seconds)
        while time.monotonic() < deadline:
            result["transport"]["recv_calls"] += 1
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                result["transport"]["timeout_returns"] += 1
                continue
            if not raw:
                result["transport"]["empty_recv_returns"] += 1
                continue
            result["transport"]["nonempty_recv_returns"] += 1
            result["transport"]["total_received_chars"] += len(raw)
            for line in raw.splitlines():
                result["transport"]["raw_frames"] += 1
                if not line:
                    continue
                try:
                    decoded = json.loads(line)
                    result["transport"]["json_frames"] += 1
                    frame = inspect_frame(decoded)
                except (ValueError, TypeError):
                    result["transport"]["frame_previews"].append(
                        {"kind": "invalid_json", "preview": str(line)[:240]}
                    )
                    continue
                if frame["kind"] == "ping":
                    result["transport"]["ping_frames"] += 1
                    ws.send("{}")
                elif frame["kind"] == "error":
                    raise RuntimeError(frame["error"])
                elif frame["kind"] == "publication" and frame.get("side") in events:
                    result["transport"]["publication_frames"] += 1
                    if not frame.get("levels"):
                        result["transport"]["zero_level_publications"] += 1
                    events[frame["side"]].append({
                        "side": frame["side"],
                        "received_after_start_ms": round((time.monotonic() - started) * 1000),
                        "levels": int(frame.get("levels") or 0),
                        "price": frame.get("top_price"),
                        "quantity": frame.get("top_quantity"),
                        "metadata_fields": frame.get("timestamp_fields", []),
                    })
                else:
                    result["transport"]["ignored_frames"] += 1
                    push = decoded.get("push") if isinstance(decoded, dict) else None
                    if isinstance(push, dict):
                        channel = push.get("channel")
                        if channel and channel not in result["transport"]["unknown_push_channels"]:
                            result["transport"]["unknown_push_channels"].append(str(channel)[:160])
                    if len(result["transport"]["frame_previews"]) < 6:
                        from wallex_centrifugo_diagnostic import _safe_payload_preview
                        result["transport"]["frame_previews"].append({
                            "kind": frame.get("kind", "unknown"),
                            "preview": _safe_payload_preview(decoded, max_chars=500),
                        })
        result["rest_after"] = _rest_snapshot()
        result["sides"] = {
            side: _side_summary(events[side], result["rest_before"], result["rest_after"], int(min_messages))
            for side in ("bid", "ask")
        }
        result["transport"]["event_counts"] = {side: len(items) for side, items in events.items()}
        result["transport"]["socket_connected_after_observation"] = bool(getattr(ws, "connected", False))
        result["received_channels"] = [
            CHANNELS[0] if events["bid"] else None,
            CHANNELS[1] if events["ask"] else None,
        ]
        result["received_channels"] = [item for item in result["received_channels"] if item]
        result["status"] = (
            "candidate" if all(result["sides"][side]["status"] == "candidate" for side in ("bid", "ask"))
            else "failed"
        )
        result["interpretation"] = (
            "candidate فقط یعنی در این بازه نمونه‌های کافی و تطبیق تقریبی با یکی از دو snapshot REST دیده شد؛ "
            "این نتیجه snapshot بودن پیام‌ها، ترتیب کامل، بازیابی شکاف یا تازگی سمت صرافی را ثابت نمی‌کند."
        )
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
        result["status"] = "failed"
        return result
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
