"""Helpers for the staged ten-run Wallex REST/reconnect validation."""
GAP_SCHEDULE = (2, 5, 10, 2, 5, 10, 2, 5, 10, 2)


def next_gap_seconds(completed_runs):
    index = int(completed_runs)
    if index < 0 or index >= len(GAP_SCHEDULE):
        raise IndexError("The ten-run validation is already complete")
    return GAP_SCHEDULE[index]


def summarize_runs(runs):
    rows = list(runs or [])
    total = len(rows)
    candidates = sum(1 for row in rows if row.get("status") == "candidate")
    failed = total - candidates
    bid_ok = sum(
        1 for row in rows
        if row.get("post_rest_ws_comparison", {}).get("bid", {}).get("status") == "candidate"
    )
    ask_ok = sum(
        1 for row in rows
        if row.get("post_rest_ws_comparison", {}).get("ask", {}).get("status") == "candidate"
    )
    return {
        "total": total,
        "candidate": candidates,
        "failed": failed,
        "candidate_rate_pct": round(candidates / total * 100, 1) if total else 0.0,
        "bid_candidate": bid_ok,
        "ask_candidate": ask_ok,
        "complete": total >= len(GAP_SCHEDULE),
        "scanner_feed_enabled": False,
        "execution_allowed": False,
        "gap_recovery_verified": False,
        "sequence_order_verified": False,
    }
