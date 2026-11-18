"""End-to-end test of the worker pipeline with fake books and an in-memory DB.

Run from the project folder:  python tests/test_pipeline.py
"""
import copy
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import worker
from stability import update_stability
from validation import build_entry, reprice_entry, process_pending
from scanner import scan_markets


def book(asks, bids, name, now, upd=None):
    return {"asks": asks, "bids": bids, "updated_at": upd, "received_at": now,
            "latency_ms": 40, "source": name}


def make_books(now, shift=0.0):
    wallex = {"ABC/IRT": book([(1000, 5000), (1001, 5000)], [(995, 9000)], "Wallex", now)}
    nobitex = {"ABC/IRT": book([(1020, 9000)],
                               [(1030 * (1 + shift), 5000), (1027 * (1 + shift), 5000)],
                               "Nobitex", now, upd=now - 2)}
    return wallex, nobitex, []


class FakeDB:
    def __init__(self):
        self.tables = {"arb_scans": [], "arb_state": [], "arb_validations": []}
        self.next_id = 1

    def select(self, table, **params):
        rows = self.tables[table]
        for key, cond in params.items():
            if key in ("select", "order", "limit"):
                continue
            op, _, val = cond.partition(".")
            assert op == "eq", cond
            want = {"true": True, "false": False}.get(val, val)
            rows = [r for r in rows if r.get(key) == want]
        return copy.deepcopy(rows)

    def insert(self, table, rows):
        for r in rows:
            r = copy.deepcopy(r)
            if table == "arb_validations":
                r["id"] = self.next_id
                self.next_id += 1
                r["created_at"] = r.get("created_at") or time.time()
            self.tables[table].append(r)

    def upsert(self, table, rows, on_conflict):
        for r in rows:
            self.tables[table] = [x for x in self.tables[table] if x[on_conflict] != r[on_conflict]]
            self.tables[table].append(copy.deepcopy(r))

    def patch(self, table, filters, values):
        row_id = int(filters["id"].split(".")[1])
        for r in self.tables[table]:
            if r["id"] == row_id:
                r.update(copy.deepcopy(values))

    def delete(self, table, filters):
        pass


def cfg():
    c = worker.load_config()
    c.update(capital=2_000_000, min_net=0.25, min_executable=100_000, horizons=(60, 300))
    return c


def test_reprice_matches_scanner():
    now = time.time()
    books = make_books(now)
    r = scan_markets(books=books)
    item = [o for o in r["opportunities"] if o["buy_exchange"] == "Wallex"][0]
    entry = build_entry(item, cfg())
    out = reprice_entry(entry, books[0], books[1])
    assert out["status"] == "ok"
    assert abs(out["profit_toman"] - item["profit_toman"]) <= 1, (out, item["profit_toman"])
    r = scan_markets(books=books, withdrawal_fees={"ABC": 5})
    item = [o for o in r["opportunities"] if o["buy_exchange"] == "Wallex"][0]
    out = reprice_entry(build_entry(item, cfg()), books[0], books[1])
    assert abs(out["profit_toman"] - item["profit_toman"]) <= 1
    print("reprice == scanner: ok")


def test_stability_counts_and_reset():
    now = time.time()
    opps = scan_markets(books=make_books(now))["opportunities"]
    routes = {}
    counts = []
    for _ in range(5):
        _, routes, checks = update_stability(opps, routes, 0.25, 100_000)
        counts.append(routes["ABC/IRT|Wallex|Nobitex"]["count"])
    assert counts == [1, 2, 3, 4, 5], counts
    moved = scan_markets(books=make_books(now, shift=0.01))["opportunities"]
    _, routes2, checks2 = update_stability(moved, routes, 0.25, 100_000)
    assert checks2["ABC/IRT|Wallex|Nobitex"]["passed"] is False
    assert routes2["ABC/IRT|Wallex|Nobitex"]["count"] == 1
    _, routes3, _ = update_stability([], routes, 0.25, 100_000)
    assert routes3 == {}
    print("stability: ok")


def test_worker_pipeline():
    c = cfg()
    db = FakeDB()
    state = {"settings": worker.settings_signature(c), "routes": {}, "last_validation": {}}
    t0 = time.time()
    worker.notify_new_stable = lambda *a, **k: None
    for i in range(5):
        now = t0 + i * 30
        worker.run_cycle(db, c, state, i + 1, now=now, books=make_books(now))
    vals = db.tables["arb_validations"]
    assert len(vals) == 1 and vals[0]["done"] is False, vals
    created = vals[0]["created_at"]
    now = t0 + 4 * 30 + 30
    worker.run_cycle(db, c, state, 6, now=now, books=make_books(now))
    assert len(db.tables["arb_validations"]) == 1
    now = created + 70
    worker.run_cycle(db, c, state, 7, now=now, books=make_books(now))
    r = db.tables["arb_validations"][0]["results"]
    assert "60" in r and r["60"]["status"] == "ok" and r["60"]["profit_toman"] > 0, r
    assert db.tables["arb_validations"][0]["done"] is False
    now = created + 310
    worker.run_cycle(db, c, state, 8, now=now, books=make_books(now, shift=-0.04))
    row = db.tables["arb_validations"][0]
    assert row["results"]["300"]["profit_toman"] < 0 and row["done"] is True, row
    before = copy.deepcopy(state["routes"])
    worker.run_cycle(db, c, state, 9, now=now + 30, books=({}, {}, ["Wallex API: boom"]))
    assert state["routes"] == before
    assert len(db.tables["arb_state"]) == 1
    print("worker pipeline: ok")


def test_missed_and_depth_failure():
    now = time.time()
    books = make_books(now)
    item = [o for o in scan_markets(books=books)["opportunities"] if o["buy_exchange"] == "Wallex"][0]
    entry = build_entry(item, cfg())
    thin = make_books(now)
    thin[0]["ABC/IRT"]["asks"] = [(1000, 1)]
    assert reprice_entry(entry, thin[0], thin[1])["status"] == "insufficient_buy_depth"
    rows = [{"id": 1, "created_at": now - 5000, "entry": entry, "results": {}, "done": False}]
    ups = process_pending(rows, books[0], books[1], now, (60, 300))
    assert ups[0][1]["60"]["status"] == "missed" and ups[0][2] is True
    print("failure paths: ok")


if __name__ == "__main__":
    test_reprice_matches_scanner()
    test_stability_counts_and_reset()
    test_worker_pipeline()
    test_missed_and_depth_failure()
    print("ALL OK")
