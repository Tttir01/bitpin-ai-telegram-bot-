"""SQLite persistence for the staged ten-run Wallex validation.

The database survives browser refreshes and Streamlit reruns. On Render Free,
the local filesystem is ephemeral, so a service restart/redeploy can still
remove this database unless a persistent disk or external database is configured.
"""
import json
import os
import sqlite3
from pathlib import Path

GAP_SCHEDULE = (2, 5, 10, 2, 5, 10, 2, 5, 10, 2)


def next_gap_seconds(completed_runs):
    index = int(completed_runs)
    if index < 0 or index >= len(GAP_SCHEDULE):
        raise IndexError("The ten-run validation is already complete")
    return GAP_SCHEDULE[index]


def _database_path(db_path=None):
    configured = db_path or os.environ.get("WALLEX_VALIDATION_DB_PATH")
    return Path(configured) if configured else Path(__file__).resolve().parent / "data" / "wallex_validation.sqlite3"


def _connect(db_path=None):
    path = _database_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=15)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS wallex_validation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_number INTEGER NOT NULL UNIQUE,
            recorded_at_utc TEXT NOT NULL,
            gap_seconds INTEGER,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
    """)
    connection.commit()
    return connection


def load_runs(db_path=None):
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM wallex_validation_runs ORDER BY run_number"
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def save_run(run, db_path=None):
    run_number = int(run["run_number"])
    payload = json.dumps(run, ensure_ascii=False, separators=(",", ":"))
    with _connect(db_path) as connection:
        connection.execute(
            """INSERT INTO wallex_validation_runs
               (run_number, recorded_at_utc, gap_seconds, status, payload_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                run_number,
                str(run.get("recorded_at_utc", "")),
                run.get("gap_seconds"),
                str(run.get("status", "failed")),
                payload,
            ),
        )
        connection.commit()


def clear_runs(db_path=None):
    with _connect(db_path) as connection:
        connection.execute("DELETE FROM wallex_validation_runs")
        connection.commit()


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
