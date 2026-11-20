"""ذخیره تاریخچه اسکن‌ها در SQLite."""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


def connect(db_path: str):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True) if Path(db_path).parent != Path('.') else None
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS scans (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      started_at TEXT NOT NULL,
      finished_at TEXT NOT NULL,
      wallex_books INTEGER NOT NULL DEFAULT 0,
      nobitex_books INTEGER NOT NULL DEFAULT 0,
      common_symbols INTEGER NOT NULL DEFAULT 0,
      accepted_count INTEGER NOT NULL DEFAULT 0,
      rejected_count INTEGER NOT NULL DEFAULT 0,
      settings_json TEXT NOT NULL,
      errors_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS opportunities (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
      symbol TEXT NOT NULL,
      buy_exchange TEXT NOT NULL,
      sell_exchange TEXT NOT NULL,
      buy_vwap REAL,
      sell_vwap REAL,
      quantity REAL,
      gross_profit_toman REAL,
      estimated_cost_toman REAL,
      estimated_net_profit_toman REAL,
      estimated_net_return_pct REAL,
      freshness_verified INTEGER NOT NULL,
      eligible INTEGER NOT NULL,
      rejection_reason TEXT,
      assumptions_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_opportunities_scan ON opportunities(scan_id);
    """)
    return conn


def save_scan(db_path: str, started_at: str, result: dict, settings: dict) -> int:
    finished = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO scans(started_at,finished_at,wallex_books,nobitex_books,
               common_symbols,accepted_count,rejected_count,settings_json,errors_json)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (started_at, finished, result.get("wallex_books", 0),
             result.get("nobitex_books", 0), result.get("common_symbols", 0),
             result.get("accepted_count", 0), result.get("rejected_count", 0),
             json.dumps(settings, ensure_ascii=False),
             json.dumps(result.get("errors", []), ensure_ascii=False)),
        )
        scan_id = cur.lastrowid
        for item in result.get("opportunities", []):
            conn.execute(
                """INSERT INTO opportunities(scan_id,symbol,buy_exchange,sell_exchange,
                   buy_vwap,sell_vwap,quantity,gross_profit_toman,estimated_cost_toman,
                   estimated_net_profit_toman,estimated_net_return_pct,freshness_verified,
                   eligible,rejection_reason,assumptions_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (scan_id, item["symbol"], item["buy_exchange"], item["sell_exchange"],
                 item.get("buy_vwap"), item.get("sell_vwap"), item.get("quantity"),
                 item.get("gross_profit_toman"), item.get("estimated_cost_toman"),
                 item.get("estimated_net_profit_toman"), item.get("estimated_net_return_pct"),
                 int(item.get("freshness_verified", False)), int(item.get("eligible", False)),
                 item.get("rejection_reason"), json.dumps(item.get("assumptions", {}), ensure_ascii=False)),
            )
    return scan_id
