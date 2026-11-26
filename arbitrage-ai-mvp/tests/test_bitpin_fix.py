import unittest
from types import SimpleNamespace
from unittest.mock import patch
import time

from scanner import _retry_delay, normalize_symbol, parse_levels, scan_markets


class BitpinFixRegressionTests(unittest.TestCase):
    def test_symbol_normalization(self):
        self.assertEqual(normalize_symbol("BTCIRT", ("USDT", "IRT")), "BTC/IRT")

    def test_orderbook_levels_are_sorted_and_invalid_rows_removed(self):
        levels = [["101", "2"], ["99", "1"], ["bad", "3"], ["100", "0"]]
        self.assertEqual(parse_levels(levels, "ask"), [(99.0, 1.0), (101.0, 2.0)])
        self.assertEqual(parse_levels(levels, "bid"), [(101.0, 2.0), (99.0, 1.0)])

    def test_retry_after_is_bounded(self):
        response = SimpleNamespace(headers={"Retry-After": "120"})
        self.assertEqual(_retry_delay(response, 0), 30.0)

    @patch("scanner.nobitex_books")
    @patch("scanner.wallex_books")
    def test_missing_wallex_exchange_timestamp_is_not_paper_eligible(self, mock_wallex, mock_nobitex):
        received = time.time()
        mock_wallex.return_value = {
            "BTC/IRT": {"asks": [(100.0, 10.0)], "bids": [(99.0, 10.0)],
                        "updated_at": None, "received_at": received,
                        "latency_ms": 10, "source": "Wallex"}
        }
        mock_nobitex.return_value = {
            "BTC/IRT": {"asks": [(110.0, 10.0)], "bids": [(109.0, 10.0)],
                        "updated_at": received, "received_at": received,
                        "latency_ms": 10, "source": "Nobitex"}
        }
        result = scan_markets(fee_local=0, fee_global=0, slippage_pct=0,
                              transfer_cost_pct=0, capital_toman=100000)
        self.assertFalse([
            item for item in result.get("opportunities", [])
            if item.get("market_data_status") == "داده بازار مناسب شبیه‌سازی"
        ])
        self.assertTrue(all(item.get("execution_allowed") is False
                            for item in result.get("potential_opportunities", [])))


if __name__ == "__main__":
    unittest.main(verbosity=2)
