"""Direct, read-only WebSocket handshake probe for Wallex Socket.IO.

The official exchange docs demonstrate Socket.IO v2.5.0 with websocket-only
transport. This probe tests the actual WebSocket upgrade, not HTTP polling.
It never subscribes to private channels or sends trading commands.
"""
from websocket import create_connection, WebSocketBadStatusException, WebSocketTimeoutException

URL = "wss://api.wallex.ir/socket.io/"
ORIGIN = "https://wallex.ir"


def probe(engine_io_version: int) -> bool:
    ws = None
    try:
        ws = create_connection(
            URL,
            timeout=8,
            origin=ORIGIN,
            header={"User-Agent": "ArbitrageMVP-ReadOnly/1.0"},
            # Explicitly test the transport documented by Wallex.
            subprotocols=None,
            enable_multithread=False,
            suppress_origin=False,
            # Query string is passed as part of URL.
        ) if False else create_connection(
            f"{URL}?EIO={engine_io_version}&transport=websocket",
            timeout=8,
            origin=ORIGIN,
            header=["User-Agent: ArbitrageMVP-ReadOnly/1.0"],
        )
        packet = ws.recv()
        print(f"EIO v{engine_io_version}: WebSocket upgrade OK; first_packet={packet[:180]!r}")
        # Engine.IO open packet begins with '0'. Complete Socket.IO namespace
        # connection (40) only; do not subscribe or interact with accounts.
        if isinstance(packet, str) and packet.startswith("0"):
            ws.send("40")
            try:
                reply = ws.recv()
                print(f"EIO v{engine_io_version}: namespace_reply={reply[:180]!r}")
            except WebSocketTimeoutException:
                print(f"EIO v{engine_io_version}: upgrade succeeded; namespace reply timed out")
        return True
    except WebSocketBadStatusException as exc:
        body = getattr(exc, "resp_body", b"")
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        print(f"EIO v{engine_io_version}: HTTP upgrade rejected; status={exc.status_code}; body={str(body)[:240]!r}")
    except Exception as exc:
        print(f"EIO v{engine_io_version}: {type(exc).__name__}: {exc}")
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
    return False


if __name__ == "__main__":
    outcomes = [probe(version) for version in (3, 4)]
    if not any(outcomes):
        print("DIRECT_WEBSOCKET_UNAVAILABLE_FROM_THIS_RUNNER")
    else:
        print("DIRECT_WEBSOCKET_REACHABLE_FROM_THIS_RUNNER")
