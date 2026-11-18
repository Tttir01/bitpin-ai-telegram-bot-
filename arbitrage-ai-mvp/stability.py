"""Pure scan-to-scan stability rules; no I/O."""
import math

from risk_gates import (
    MAX_MATCHED_VOLUME_CHANGE_PCT,
    MAX_STABILITY_PROFIT_DROP_PCT,
    allowed_vwap_change_pct,
)


def make_route_id(symbol, buy_exchange, sell_exchange):
    return f"{symbol}|{buy_exchange}|{sell_exchange}"


def _number(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _snapshot(item):
    return {
        "buy_vwap": _number(item.get("buy_vwap")),
        "sell_vwap": _number(item.get("sell_vwap")),
        "base_quantity": _number(item.get("base_quantity")),
        "profit_toman": _number(item.get("profit_toman")),
    }


def eligible_routes(opportunities, min_net, min_executable):
    eligible = {}
    for item in opportunities or []:
        net = _number(item.get("net_spread_pct"), -999.0)
        profit = _number(item.get("profit_toman"), -1.0)
        capital = _number(item.get("used_capital_toman"), -1.0)
        if net < min_net or profit <= 0 or capital < min_executable or capital <= 0:
            continue
        route_id = make_route_id(
            item.get("symbol"), item.get("buy_exchange"), item.get("sell_exchange")
        )
        eligible[route_id] = item
    return eligible


def update_stability(opportunities, previous_routes, min_net, min_executable):
    previous_routes = previous_routes or {}
    eligible = eligible_routes(opportunities, min_net, min_executable)
    new_routes, checks = {}, {}

    for route_id, item in eligible.items():
        current = _snapshot(item)
        previous = previous_routes.get(route_id) or {}
        prior = previous.get("snapshot")
        passed = False
        check = {"passed": False}

        if prior:
            def move(key):
                old = _number(prior.get(key))
                new = _number(current.get(key))
                return abs(new / old - 1.0) * 100 if old > 0 else 999.0

            buy_move = move("buy_vwap")
            sell_move = move("sell_vwap")
            volume_move = move("base_quantity")
            old_profit = _number(prior.get("profit_toman"))
            if old_profit > 0:
                profit_change = (current["profit_toman"] / old_profit - 1.0) * 100
                profit_drop = max(0.0, -profit_change)
            else:
                profit_change, profit_drop = None, 999.0

            limit = allowed_vwap_change_pct(item.get("net_spread_pct"))
            passed = bool(
                buy_move <= limit
                and sell_move <= limit
                and volume_move <= MAX_MATCHED_VOLUME_CHANGE_PCT
                and profit_drop <= MAX_STABILITY_PROFIT_DROP_PCT
            )
            check = {
                "passed": passed,
                "buy_move_pct": round(buy_move, 6),
                "sell_move_pct": round(sell_move, 6),
                "volume_move_pct": round(volume_move, 6),
                "profit_change_pct": (
                    round(profit_change, 6) if profit_change is not None else None
                ),
                "profit_drop_pct": round(profit_drop, 6),
                "vwap_limit_pct": round(limit, 6),
            }

        old_count = int(previous.get("count", 0) or 0)
        count = old_count + 1 if passed and old_count > 0 else 1
        new_routes[route_id] = {"count": count, "snapshot": current}
        check["stable_scans"] = count
        checks[route_id] = check

    # Routes absent from this successful snapshot are intentionally reset.
    return eligible, new_routes, checks
