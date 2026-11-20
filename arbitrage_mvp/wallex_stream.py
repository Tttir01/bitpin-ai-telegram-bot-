"""دریافت تشخیصی snapshot دفتر سفارش والکس از Socket.IO؛ بدون سفارش."""
import time
from scanner import get_json, _levels, normalize_symbol, WALLEX


def _market_symbols():
    payload = get_json(f"{WALLEX}/v2/depth/all", timeout=15)
    data = payload.get("result") or payload.get("data") or {}
    if isinstance(data, dict) and isinstance(data.get("symbols"), dict):
        data = data["symbols"]
    if not isinstance(data, dict):
        raise ValueError("ساختار فهرست بازارهای والکس معتبر نیست.")
    return sorted(
        str(symbol).upper()
        for symbol in data
        if str(symbol).upper().endswith(("TMN", "IRT"))
    )


def _stream_levels(payload, side):
    """پیام Broadcaster والکس ممکن است دیکشنری با کلیدهای عددی باشد."""
    if isinstance(payload, dict):
        try:
            payload = [payload[k] for k in sorted(payload, key=lambda x: int(x))]
        except (ValueError, TypeError):
            payload = list(payload.values())
    return _levels(payload, side)


def collect_wallex_stream(wait_seconds=8):
    """برای هر بازار تومانی، هر دو کانال عمق را می‌گیرد.

    timestamp سمت سرور در نمونه پیام عمق والکس مستند نشده است؛
    received_at صرفاً زمان دریافت محلی است و نباید به‌عنوان زمان صرافی تفسیر شود.
    """
    if not 1 <= wait_seconds <= 30:
        raise ValueError("wait_seconds باید بین 1 تا 30 باشد.")
    try:
        import socketio
    except ImportError as exc:
        raise RuntimeError(
            "وابستگی Socket.IO نصب نیست؛ pip install -r requirements.txt را اجرا کنید."
        ) from exc

    symbols = _market_symbols()
    if not symbols:
        raise ValueError("بازار تومانی برای اشتراک پیدا نشد.")

    received = {}
    client = socketio.Client(
        reconnection=True, logger=True, engineio_logger=True,
    )

    @client.on("Broadcaster")
    def on_broadcaster(channel, data):
        if not isinstance(channel, str) or not isinstance(data, (dict, list)):
            return
        if channel.endswith("@sellDepth"):
            raw_symbol, side = channel[:-len("@sellDepth")], "ask"
        elif channel.endswith("@buyDepth"):
            raw_symbol, side = channel[:-len("@buyDepth")], "bid"
        else:
            return
        symbol = normalize_symbol(raw_symbol, ("USDT", "USDC", "TMN", "IRT"))
        try:
            levels = _stream_levels(data, side)
        except Exception:
            return
        if levels:
            row = received.setdefault(symbol, {})
            row[side] = levels
            row[side + "_received_at"] = time.time()

    try:
        client.connect(
            WALLEX, transports=["websocket"],
            socketio_path="socket.io",
        )
        for raw_symbol in symbols:
            client.emit("subscribe", {"channel": raw_symbol + "@sellDepth"})
            client.emit("subscribe", {"channel": raw_symbol + "@buyDepth"})
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if all("ask" in row and "bid" in row for row in received.values()) and len(received) >= len(symbols):
                break
            time.sleep(0.1)
    finally:
        if client.connected:
            client.disconnect()

    result = {}
    for symbol, row in received.items():
        if "ask" not in row or "bid" not in row:
            continue
        result[symbol] = {
            "asks": row["ask"],
            "bids": row["bid"],
            "received_at": max(row["ask_received_at"], row["bid_received_at"]),
            "exchange_timestamp": None,
            "timestamp_quality": "local_receive_only",
            "source": "Wallex Socket.IO",
        }
    return {
        "markets_requested": len(symbols),
        "books_received": len(result),
        "books": result,
        "warning": (
            "زمان سمت سرور در پیام عمق والکس موجود نیست؛ زمان دریافت محلی است. "
            "این snapshot به‌تنهایی مجوز پذیرش سیگنال یا معامله نیست."
        ),
    }
