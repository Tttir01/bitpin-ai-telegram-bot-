"""Read-only probe for the currently documented Wallex Centrifugo depth stream.

This diagnostic never feeds the arbitrage scanner or its eligibility gate.
The public orderbook publications documented by Wallex contain no exchange
timestamp/offset and subscriptions do not provide an initial snapshot.
"""
import json
import time

import websocket

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


def main(wait_seconds=12):
    ws = websocket.create_connection(URL, timeout=8, enable_multithread=True)
    try:
        ws.settimeout(2)
        ws.send(json.dumps({"id": 1, "connect": {}}))
        connected = False
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            for line in raw.split("\n"):
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("id") == 1 and "connect" in msg:
                    connected = True
                    print("CENTRIFUGO_CONNECT_OK")
                    break
                if "error" in msg:
                    print(f"CONNECT_ERROR: {msg['error']}")
                    return
            if connected:
                break
        if not connected:
            print("CENTRIFUGO_CONNECT_ACK_TIMEOUT")
            return

        for index, channel in enumerate(CHANNELS, start=2):
            ws.send(json.dumps({"id": index, "subscribe": {"channel": channel}}))

        subscribed = set()
        publications = 0
        timestamp_fields = []
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            for line in raw.split("\n"):
                if not line:
                    continue
                if line == "{}":
                    ws.send("{}")
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "error" in msg:
                    print(f"SERVER_ERROR: {msg['error']}")
                    continue
                if "subscribe" in msg and "id" in msg:
                    subscribed.add(msg["id"])
                    print(f"SUBSCRIBE_ACK id={msg['id']}")
                    continue
                push = msg.get("push")
                if not isinstance(push, dict):
                    continue
                channel = push.get("channel", "")
                data = (push.get("pub") or {}).get("data")
                if channel not in CHANNELS:
                    continue
                publications += 1
                if isinstance(data, dict):
                    timestamp_fields.extend(
                        f"{channel}.{key}" for key in data if key in TIMESTAMP_KEYS
                    )
                elif isinstance(data, list):
                    for level in data[:3]:
                        if isinstance(level, dict):
                            timestamp_fields.extend(
                                f"{channel}[].{key}" for key in level if key in TIMESTAMP_KEYS
                            )
                print(f"DEPTH_PUBLICATION channel={channel} levels={len(data) if isinstance(data, list) else 'n/a'}")
        print(f"SUBSCRIBED_ACKS={len(subscribed)}/2")
        print(f"DEPTH_PUBLICATIONS={publications}")
        print(f"TIMESTAMP_OR_SEQUENCE_FIELDS={timestamp_fields or 'none observed'}")
        print("NOTE: connection receive time is diagnostic only, not exchange book time.")
        print("NOTE: no publication during the wait may simply mean the book did not change.")
    finally:
        ws.close()


if __name__ == "__main__":
    main()
