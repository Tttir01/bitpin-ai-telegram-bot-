"""Authenticated READ-only Nobitex wallet access (Ed25519)."""
import base64
import os
import time

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

NOBITEX_API = "https://apiv2.nobitex.ir"


def _private_key(value):
    value = value.strip()
    if value.startswith("-----BEGIN"):
        key = serialization.load_pem_private_key(value.encode("utf-8"), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Nobitex private key must be Ed25519.")
        return key
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), validate=True)
    except Exception as exc:
        raise ValueError("NOBITEX_API_PRIVATE_KEY must be a base64 Ed25519 private key or PEM.") from exc
    if len(raw) == 64:
        raw = raw[:32]
    if len(raw) != 32:
        raise ValueError("Decoded Ed25519 private key must be 32 bytes (or 64-byte secret key).")
    return Ed25519PrivateKey.from_private_bytes(raw)


def read_nobitex_balances():
    """Fetch wallet list only. No trading, transfer, or withdrawal endpoints."""
    public_key = os.getenv("NOBITEX_API_PUBLIC_KEY", "").strip()
    private_value = os.getenv("NOBITEX_API_PRIVATE_KEY", "").strip()
    if not public_key or not private_value:
        return {"configured": False, "balances": [], "message": "Nobitex read-only keys are not configured."}

    method = "GET"
    path = "/users/wallets/list"
    body = ""
    timestamp = str(int(time.time()))
    message = (timestamp + method + path + body).encode("utf-8")
    signature = base64.urlsafe_b64encode(_private_key(private_value).sign(message)).decode("ascii").rstrip("=")

    response = requests.get(
        NOBITEX_API + path,
        headers={
            "Nobitex-Key": public_key,
            "Nobitex-Signature": signature,
            "Nobitex-Timestamp": timestamp,
            "Accept": "application/json",
        },
        timeout=(5, 18),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("status") not in ("ok", "success"):
        raise RuntimeError("Nobitex wallet API returned an unsuccessful response.")

    raw = payload.get("wallets") or payload.get("result") or payload.get("data") or []
    if isinstance(raw, dict):
        raw = raw.get("wallets") or raw.get("items") or []
    balances = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            balances.append({
                "ارز": item.get("currency") or item.get("symbol") or item.get("code") or "—",
                "موجودی کل": item.get("balance", item.get("total", "—")),
                "قابل برداشت/استفاده": item.get("activeBalance", item.get("available", item.get("usable", "—"))),
                "بلوکه": item.get("blockedBalance", item.get("locked", "—")),
            })
    return {"configured": True, "balances": balances, "message": "Read-only wallet data loaded."}
