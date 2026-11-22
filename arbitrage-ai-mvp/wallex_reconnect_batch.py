"""SQLite persistence and safe JSON recovery for Wallex validation runs.

Render Free local storage is ephemeral. Exported JSON reports can be imported
again after a restart/redeploy. Safety flags intentionally remain disabled.
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


def import_runs_json(raw_json, db_path=None):
    """Import an exported report without overwriting conflicting run numbers."""
    if isinstance(raw_json, bytes):
        raw_json = raw_json.decode("utf-8-sig")
    document = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    incoming = document.get("runs") if isinstance(document, dict) else None
    if not isinstance(incoming, list):
        raise ValueError("ساختار فایل معتبر نیست؛ آرایه runs در گزارش پیدا نشد.")
    if not incoming:
        raise ValueError("فایل گزارش هیچ آزمایشی ندارد.")

    valid = []
    seen = set()
    for item in incoming:
        if not isinstance(item, dict):
            raise ValueError("یکی از رکوردهای آزمایش ساختار معتبری ندارد.")
        try:
            number = int(item["run_number"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("هر آزمایش باید run_number معتبر داشته باشد.")
        if number < 1 or number > len(GAP_SCHEDULE):
            raise ValueError(f"شماره آزمایش {number} خارج از بازه ۱ تا ۱۰ است.")
        if number in seen:
            raise ValueError(f"شماره آزمایش {number} در خود فایل تکراری است.")
        seen.add(number)
        gap = item.get("gap_seconds")
        if gap is not None and int(gap) != GAP_SCHEDULE[number - 1]:
            raise ValueError(f"وقفه آزمایش {number} با برنامه ده‌مرحله‌ای مطابقت ندارد.")
        clean = dict(item)
        clean["run_number"] = number
        clean.setdefault("recorded_at_utc", "imported_without_timestamp")
        clean.setdefault("status", "failed")
        valid.append(clean)

    imported = skipped = conflicts = 0
    with _connect(db_path) as connection:
        for item in sorted(valid, key=lambda row: row["run_number"]):
            number = item["run_number"]
            existing = connection.execute(
                "SELECT payload_json FROM wallex_validation_runs WHERE run_number = ?",
                (number,),
            ).fetchone()
            payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            if existing:
                if json.loads(existing[0]) == item:
                    skipped += 1
                else:
                    conflicts += 1
                continue
            connection.execute(
                """INSERT INTO wallex_validation_runs
                   (run_number, recorded_at_utc, gap_seconds, status, payload_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (number, str(item.get("recorded_at_utc", "")),
                 item.get("gap_seconds"), str(item.get("status", "failed")), payload),
            )
            imported += 1
        connection.commit()
    return {"imported": imported, "skipped": skipped, "conflicts": conflicts}


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
