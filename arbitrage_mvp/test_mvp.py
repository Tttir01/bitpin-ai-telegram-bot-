import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import time

from scanner import normalize_symbol, _levels, scan, _retry_seconds, fetch_nobitex
from db import save_scan, connect


class MVPTests(unittest.TestCase):
    def settings(self, **overrides):
        values = dict(
            request_timeout_seconds=3, nobitex_irt_price_divisor=10,
            wallex_fee_pct=0.25, nobitex_fee_pct=0.25,
            slippage_pct_per_side=0.10, transfer_cost_pct=0.20,
            capital_toman=2_000_000, min_net_profit_toman=100,
            max_book_age_seconds=30, fees_confirmed=True,
            transfer_cost_confirmed=True,
        )
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_symbol_normalization(self):
        self.assertEqual(normalize_symbol("BTCIRT", ("IRT",)), "BTC/IRT")
        self.assertEqual(normalize_symbol("BTC_TMN", ("TMN",)), "BTC/IRT")

    def test_orderbook_levels_sorted_and_invalid_removed(self):
        levels = _levels([[100, 1], [102, 2], ["bad", 3], [101, 0]], "ask")
        self.assertEqual(levels, [(100.0, 1.0), (102.0, 2.0)])

    def test_nobitex_irt_prices_are_converted_from_rial_to_toman(self):
        payload = {
            "status": "ok",
            "BTCIRT": {
                "lastUpdate": int(time.time() * 1000),
                "asks": [["1476091000", "1.016"]],
                "bids": [["1470001120", "0.126571"]],
            },
        }
        with patch("scanner.get_json", return_value=payload):
            books = fetch_nobitex(3, irt_divisor=10)
        self.assertEqual(books["BTC/IRT"]["asks"][0][0], 147609100.0)
        self.assertEqual(books["BTC/IRT"]["bids"][0][0], 147000112.0)

    def test_missing_exchange_timestamps_reject_signal(self):
        now = time.time()
        book = {
            "asks": [(100.0, 100.0)], "bids": [(99.0, 100.0)],
            "received_at": now, "exchange_timestamp": None, "source": "test",
        }
        with patch("scanner.fetch_wallex", return_value={"BTC/IRT": book}), \
             patch("scanner.fetch_nobitex", return_value={"BTC/IRT": book}):
            result = scan(self.settings())
        self.assertEqual(len(result["opportunities"]), 2)
        self.assertEqual(result["accepted_count"], 0)
        self.assertTrue(all(not x["freshness_verified"] for x in result["opportunities"]))
        self.assertTrue(all("زمان سمت سرور" in x["rejection_reason"] for x in result["opportunities"]))

    def test_fresh_books_and_confirmed_assumptions_can_be_paper_eligible(self):
        now = time.time()
        wallex = {
            "asks": [(100.0, 100.0)], "bids": [(99.0, 100.0)],
            "received_at": now, "exchange_timestamp": now, "source": "Wallex",
        }
        nobitex = {
            "asks": [(111.0, 100.0)], "bids": [(110.0, 100.0)],
            "received_at": now, "exchange_timestamp": now, "source": "Nobitex",
        }
        with patch("scanner.fetch_wallex", return_value={"BTC/IRT": wallex}), \
             patch("scanner.fetch_nobitex", return_value={"BTC/IRT": nobitex}):
            result = scan(self.settings())
        self.assertGreaterEqual(result["accepted_count"], 1)

    def test_retry_after_is_bounded(self):
        response = SimpleNamespace(headers={"Retry-After": "120"})
        self.assertEqual(_retry_seconds(response, 0), 30.0)

    def test_sqlite_persists_scan_and_opportunities(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "history.sqlite3")
            result = {
                "wallex_books": 1, "nobitex_books": 1, "common_symbols": 1,
                "accepted_count": 0, "rejected_count": 1, "errors": [],
                "opportunities": [{
                    "symbol": "BTC/IRT", "buy_exchange": "Wallex",
                    "sell_exchange": "Nobitex", "freshness_verified": False,
                    "eligible": False, "assumptions": {},
                }],
            }
            scan_id = save_scan(path, "2026-01-01T00:00:00+00:00", result, {})
            with connect(path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM opportunities WHERE scan_id=?", (scan_id,)).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
