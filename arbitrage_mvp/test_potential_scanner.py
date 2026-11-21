import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from types import SimpleNamespace

from potential_scanner import _parse_wallex, _parse_nobitex, scan_potential


class PotentialScannerTests(unittest.TestCase):
    def test_local_receive_time_is_not_exchange_timestamp(self):
        payload = {
            "success": True,
            "result": {
                "USDTTMN": {
                    "ask": [{"price": "100", "quantity": "20"}],
                    "bid": [{"price": "99", "quantity": "20"}],
                }
            },
        }
        book = _parse_wallex(payload)["USDT/IRT"]
        self.assertIsNone(book["exchange_timestamp"])
        self.assertNotIn("received_at_utc", book)

    def test_nobitex_exchange_timestamp_only_from_payload(self):
        payload = {
            "status": "ok",
            "USDTIRT": {
                "asks": [["1010", "20"]],
                "bids": [["1000", "20"]],
            },
        }
        book = _parse_nobitex(payload, 10)["USDT/IRT"]
        self.assertIsNone(book["exchange_timestamp"])
        self.assertEqual(book["asks"][0][0], 101)

    def test_potential_candidate_never_becomes_verified_or_executable(self):
        now = datetime.now(timezone.utc).isoformat()
        feed_w = {
            "exchange": "Wallex", "received_at_utc": now,
            "request_duration_ms": 50, "received_monotonic_ns": 100,
            "books": {"USDT/IRT": {
                "asks": [(100.0, 100000)], "bids": [(99.0, 100000)],
                "exchange_timestamp": None,
            }},
        }
        feed_n = {
            "exchange": "Nobitex", "received_at_utc": now,
            "request_duration_ms": 60, "received_monotonic_ns": 110,
            "books": {"USDT/IRT": {
                "asks": [(111.0, 100000)], "bids": [(110.0, 100000)],
                "exchange_timestamp": None,
            }},
        }
        settings = SimpleNamespace(
            request_timeout_seconds=5, nobitex_irt_price_divisor=10,
            wallex_fee_pct=0.01, nobitex_fee_pct=0.01,
            slippage_pct_per_side=0.01, transfer_cost_pct=0.01,
            capital_toman=2_000_000, min_net_profit_toman=1,
        )
        with patch("potential_scanner._collect", return_value=({"Wallex": feed_w, "Nobitex": feed_n}, [])):
            result = scan_potential(settings)
        self.assertTrue(result["potential_opportunities"])
        for item in result["potential_opportunities"]:
            self.assertFalse(item["verified"])
            self.assertFalse(item["eligible"])
            self.assertFalse(item["execution_allowed"])
            self.assertEqual(item["status"], "POTENTIAL_ONLY_LOCAL_RECEIVE_TIME")
            self.assertFalse(item["exchange_timestamps_present"])


if __name__ == "__main__":
    unittest.main()
