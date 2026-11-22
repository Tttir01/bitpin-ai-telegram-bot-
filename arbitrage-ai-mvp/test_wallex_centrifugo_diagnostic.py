import unittest

from wallex_centrifugo_diagnostic import (
    CHANNELS, inspect_frame, _extract_side_levels, _find_wallex_symbol_book,
)


class CentrifugoFrameTests(unittest.TestCase):
    def test_connect_ack(self):
        self.assertEqual(inspect_frame({"id": 1, "connect": {}})["kind"], "connect_ack")

    def test_subscription_ack(self):
        frame = inspect_frame({"id": 2, "subscribe": {"recoverable": False}})
        self.assertEqual(frame, {"kind": "subscribe_ack", "id": 2})

    def test_depth_publication_is_diagnostic_only(self):
        frame = inspect_frame({
            "push": {
                "channel": CHANNELS[0],
                "pub": {"data": [{"price": "1", "quantity": "2"}]},
            }
        })
        self.assertEqual(frame["kind"], "publication")
        self.assertEqual(frame["channel"], CHANNELS[0])
        self.assertEqual(frame["levels"], 1)
        self.assertEqual(frame["timestamp_fields"], [])

    def test_timestamp_fields_are_reported_not_trusted(self):
        frame = inspect_frame({
            "push": {
                "channel": CHANNELS[1],
                "pub": {"data": {"timestamp": 123, "bids": []}},
            }
        })
        self.assertEqual(frame["timestamp_fields"], ["timestamp"])

    def test_ping_and_server_error(self):
        self.assertEqual(inspect_frame({})["kind"], "ping")
        self.assertEqual(inspect_frame({"error": {"code": 1}})["kind"], "error")

    def test_extracts_sorted_rest_bid_and_ask_levels(self):
        book = {
            "bid": [["100", "2"], ["101", "1"]],
            "ask": [["103", "3"], ["102", "4"]],
        }
        self.assertEqual(_extract_side_levels(book, "bid")[0], (101.0, 1.0))
        self.assertEqual(_extract_side_levels(book, "ask")[0], (102.0, 4.0))

    def test_extracts_levels_from_centrifugo_publication(self):
        payload = {"data": {"bids": [{"price": "99", "quantity": "5"}]}}
        self.assertEqual(_extract_side_levels(payload, "bid")[0], (99.0, 5.0))

    def test_finds_expected_wallex_symbol_book(self):
        payload = {"success": True, "result": {"symbols": {"USDTTMN": {"bid": [], "ask": []}}}}
        self.assertEqual(_find_wallex_symbol_book(payload), {"bid": [], "ask": []})

    def test_rejects_invalid_rest_payload(self):
        with self.assertRaises(RuntimeError):
            _find_wallex_symbol_book({"success": False, "result": {}})


if __name__ == "__main__":
    unittest.main(verbosity=2)
