import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scanner import _retry_delay, get_json, normalize_symbol, parse_levels


class RetryAfterTests(unittest.TestCase):
    @patch("scanner.time.sleep")
    @patch("scanner.requests.get")
    def test_get_json_honors_numeric_retry_after(self, mock_get, mock_sleep):
        limited = SimpleNamespace(status_code=429, headers={"Retry-After": "3"})
        success = SimpleNamespace(
            status_code=200,
            headers={},
            raise_for_status=lambda: None,
            json=lambda: {"status": "ok"},
        )
        mock_get.side_effect = [limited, success]

        self.assertEqual(get_json("https://example.test/data"), {"status": "ok"})
        mock_sleep.assert_called_once_with(3.0)
        self.assertEqual(mock_get.call_count, 2)

    @patch("scanner.time.sleep")
    @patch("scanner.requests.get")
    def test_get_json_uses_backoff_when_retry_after_missing(self, mock_get, mock_sleep):
        limited = SimpleNamespace(status_code=503, headers={})
        success = SimpleNamespace(
            status_code=200,
            headers={},
            raise_for_status=lambda: None,
            json=lambda: {"ok": True},
        )
        mock_get.side_effect = [limited, success]

        self.assertEqual(get_json("https://example.test/data"), {"ok": True})
        mock_sleep.assert_called_once_with(1.0)

    def test_retry_after_is_capped(self):
        response = SimpleNamespace(headers={"Retry-After": "120"})
        self.assertEqual(_retry_delay(response, 0), 30.0)

    def test_fallback_backoff_is_bounded(self):
        self.assertEqual(_retry_delay(SimpleNamespace(headers={}), 8), 8.0)


class NormalizationTests(unittest.TestCase):
    def test_symbol_suffix_normalization(self):
        self.assertEqual(normalize_symbol("BTCIRT", ("USDT", "IRT")), "BTC/IRT")

    def test_orderbook_levels_are_sorted_and_invalid_rows_removed(self):
        levels = [["101", "2"], ["99", "1"], ["bad", "3"], ["100", "0"]]
        self.assertEqual(parse_levels(levels, "ask"), [(99.0, 1.0), (101.0, 2.0)])
        self.assertEqual(parse_levels(levels, "bid"), [(101.0, 2.0), (99.0, 1.0)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
