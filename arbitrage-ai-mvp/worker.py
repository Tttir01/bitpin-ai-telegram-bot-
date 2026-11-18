"""Supabase-backed paper-only arbitrage worker. Never places live orders."""
import json
import os
import time
from datetime import datetime, timezone

from db import Supabase
from risk_gates import is_paper_candidate
from scanner import fetch_both_books, scan_markets
from stability import make_route_id, update_stability
from validation import build_entry, process_pending


def _float_env(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def load_config():
    return {
        "capital": _float_env("CAPITAL_TOMAN", 2_000_000),
        "fee_local": _float_env("FEE_WALLEX_PCT", _float_env("FEE_WALLEX", 0.25)) / 100
            if os.getenv("FEE_WALLEX_PCT") is not None or os.getenv("FEE_WALLEX") is not None
            else 0.0025,
        "fee_global": _float_env("FEE_NOBITEX_PCT", _float_env("FEE_NOBITEX", 0.25)) / 100
            if os.getenv("FEE_NOBITEX_PCT") is not None or os.getenv("FEE_NOBITEX") is not None
            else 0.0025,
        "slippage_pct": _float_env("SLIPPAGE_PCT", 0.20),
        "transfer_cost_pct": _float_env("TRANSFER_COST_PCT", 0.30),
        "min_net": _float_env("MIN_NET_PROFIT_PCT", 0.25),
        "min_executable": _float_env("MIN_EXECUTABLE_TOMAN", 100_000),
        "min_order_toman": _float_env("MIN_ORDER_TOMAN", 0),
        "max_book_age_seconds": int(_float_env("MAX_BOOK_AGE_SECONDS", 90)),
        "horizons": tuple(int(x.strip()) for x in os.getenv("VALIDATION_HORIZONS", "60,300,900").split(",") if x.strip()),
        "cooldown_seconds": int(_float_env("PAPER_VALIDATION_COOLDOWN_SECONDS", 1800)),
        "withdrawal_fees": {},
    }


def settings_signature(config):
    keys = (
        "capital", "fee_local", "fee_global", "slippage_pct",
        "transfer_cost_pct", "min_net", "min_executable",
        "min_order_toman", "max_book_age_seconds", "horizons",
    )
    return json.dumps({k: config.get(k) for k in keys}, sort_keys=True)


def notify_new_stable(item, stable_scans, checks=None):
    """Optional Telegram alert. Missing credentials never block the worker."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    import requests
    message = (
        "🔎 فرصت پایدار آربیتراژ — فقط شبیه‌سازی\n"
        f"{item.get('symbol')} | خرید {item.get('buy_exchange')} / فروش {item.get('sell_exchange')}\n"
        f"سرمایه: {item.get('used_capital_toman', 0):,.0f} تومان\n"
        f"سود خالص تخمینی: {item.get('profit_toman', 0):,.0f} تومان "
        f"({item.get('net_spread_pct', 0):.3f}٪)\n"
        f"پایداری: {stable_scans}/5 اسکن\n"
        "هیچ سفارش یا انتقال واقعی انجام نشده است."
    )
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
        timeout=(5, 15),
    )
    response.raise_for_status()
    return bool(response.json().get("ok"))


def _record_scan(db, run_id, now, result, status):
    db.insert("arb_scans", [{
        "run_id": int(run_id),
        "scanned_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "status": status,
        "opportunities": result.get("opportunities", []),
        "errors": result.get("errors", []),
        "diagnostics": result.get("diagnostics", {}),
        "real_orders_enabled": False,
    }])


def _save_state(db, state, now):
    db.upsert("arb_state", [{
        "state_key": "worker",
        "payload": state,
        "updated_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
    }], on_conflict="state_key")


def _settle_pending(db, config, wallex, nobitex, now):
    pending = db.select("arb_validations", select="id,created_at,entry,results,done", done="eq.false")
    updates = process_pending(pending, wallex, nobitex, now, config["horizons"])
    for row_id, results, done in updates:
        if row_id is None:
            continue
        db.patch(
            "arb_validations",
            {"id": f"eq.{row_id}"},
            {"results": results, "done": bool(done), "updated_at": datetime.fromtimestamp(now, timezone.utc).isoformat()},
        )


def run_cycle(db, config, state, run_id, now=None, books=None):
    now = time.time() if now is None else float(now)
    state.setdefault("routes", {})
    state.setdefault("last_validation", {})
    state.setdefault("settings", settings_signature(config))

    # Fetch one synchronized snapshot and reuse it for scan and delayed re-pricing.
    if books is None:
        books = fetch_both_books()
    result = scan_markets(
        fee_local=config["fee_local"],
        fee_global=config["fee_global"],
        slippage_pct=config["slippage_pct"],
        transfer_cost_pct=config["transfer_cost_pct"],
        capital_toman=config["capital"],
        max_book_age_seconds=config["max_book_age_seconds"],
        withdrawal_fees=config.get("withdrawal_fees") or {},
        min_order_toman=config.get("min_order_toman", 0),
        books=books,
        now=now,
    )

    wallex, nobitex, book_errors = books
    errors = list(result.get("errors", [])) + [e for e in book_errors if e not in result.get("errors", [])]
    no_snapshot = books is not None and not wallex and not nobitex
    scan_ok = not errors and not no_snapshot
    _record_scan(db, run_id, now, result, "ok" if scan_ok else "data_error")

    if not scan_ok:
        # An outage is not a failed market observation and must not reset streaks.
        _save_state(db, state, now)
        return result

    _settle_pending(db, config, wallex, nobitex, now)

    eligible, routes, checks = update_stability(
        result.get("opportunities", []),
        state.get("routes", {}),
        config["min_net"],
        config["min_executable"],
    )
    state["routes"] = routes
    for route_id, item in eligible.items():
        check = checks.get(route_id, {})
        stable_count = int(routes.get(route_id, {}).get("count", 0))
        prior = check.get("profit_change_pct")
        stress = item.get("stress_profit_slip_025_toman")
        if not is_paper_candidate(
            stable_scans=stable_count,
            market_stable_now=check.get("passed") is True,
            validation_status=item.get("validation_status"),
            profit_toman=item.get("profit_toman"),
            used_capital_toman=item.get("used_capital_toman"),
            capital=config["capital"],
            profit_change_pct=prior,
            stress_profit_slip_025_toman=stress,
        ):
            continue

        last = float(state["last_validation"].get(route_id, 0) or 0)
        if now - last < config["cooldown_seconds"]:
            continue
        entry = build_entry(item, config)
        db.insert("arb_validations", [{
            "route_id": route_id,
            "entry": entry,
            "initial_opportunity": item,
            "results": {},
            "done": False,
            "real_order_placed": False,
        }])
        state["last_validation"][route_id] = now
        try:
            notify_new_stable(item, stable_count, check)
        except Exception as error:
            print(f"Telegram notification failed: {type(error).__name__}")

    _save_state(db, state, now)
    return result


def main():
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured as server secrets")
    config = load_config()
    db = Supabase(url, key)
    state_rows = db.select("arb_state", select="payload", state_key="eq.worker", limit="1")
    state = state_rows[0].get("payload") if state_rows else {}
    state = state if isinstance(state, dict) else {}
    signature = settings_signature(config)
    if state.get("settings") != signature:
        state = {"settings": signature, "routes": {}, "last_validation": {}}

    run_seconds = max(30, int(_float_env("RUN_SECONDS", 270)))
    interval = max(15, int(_float_env("SCAN_INTERVAL_SECONDS", 30)))
    deadline = time.monotonic() + run_seconds
    run_id = int(time.time())
    while True:
        started = time.monotonic()
        try:
            run_cycle(db, config, state, run_id, now=time.time())
        except Exception as error:
            print(f"Worker cycle failed: {type(error).__name__}: {error}")
        run_id += 1
        remaining = deadline - time.monotonic()
        if remaining <= interval:
            break
        time.sleep(min(interval, max(0, remaining)))
    print("Worker finished; paper-only mode. No live orders were submitted.")


if __name__ == "__main__":
    main()
