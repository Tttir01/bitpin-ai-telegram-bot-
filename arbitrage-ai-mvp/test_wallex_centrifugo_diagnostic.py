import unittest

from wallex_centrifugo_diagnostic import (
    CHANNELS, inspect_frame, _extract_side_levels, _find_wallex_symbol_book,\n    _safe_payload_preview,
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
        self.assertEqual(frame["top_price"], 1.0)
        self.assertEqual(frame["top_quantity"], 2.0)

    def test_timestamp_fields_are_reported_recursively_but_not_trusted(self):
        frame = inspect_frame({
            "push": {
                "channel": CHANNELS[1],
                "pub": {"data": {"metadata": {"timestamp": 123}, "0": {"price": "2", "quantity": "3"}}},
            }
        })
        self.assertEqual(frame["timestamp_fields"], ["timestamp"])

    def test_numeric_keyed_wallex_payload_is_parsed_and_sorted(self):
        payload = {
            "1": {"price": "101", "quantity": "2"},
            "0": {"price": "100", "quantity": "1"},
        }
        self.assertEqual(_extract_side_levels(payload, "ask"), [(100.0, 1.0), (101.0, 2.0)])
        self.assertEqual(_extract_side_levels(payload, "bid"), [(101.0, 2.0), (100.0, 1.0)])

    def test_numeric_keyed_payload_inside_data_envelope(self):
        payload = {"data": {
            "1": {"price": "101", "quantity": "2"},
            "0": {"price": "100", "quantity": "1"},
        }}
        self.assertEqual(_extract_side_levels(payload, "ask")[0], (100.0, 1.0))

    def test_publication_reports_extracted_level_count_for_numeric_map(self):
        frame = inspect_frame({
            "push": {
                "channel": CHANNELS[0],
                "pub": {"data": {
                    "1": {"price": "101", "quantity": "2"},
                    "0": {"price": "100", "quantity": "1"},
                }},
            }
        })
        self.assertEqual(frame["levels"], 2)
        self.assertEqual(frame["top_price"], 101.0)
        self.assertEqual(frame["payload_shape"], "numeric_keyed_map")

    def test_publication_includes_sanitized_payload_preview(self):
        frame = inspect_frame({
            "push": {
                "channel": CHANNELS[0],
                "pub": {"data": {"unexpected": {"value": 7}, "api_key": "do-not-show"}},
            }
        })
        self.assertEqual(frame["kind"], "publication")
        self.assertIn('"unexpected"', frame["payload_preview"])
        self.assertNotIn("do-not-show", frame["payload_preview"])
        self.assertIn("[REDACTED]", frame["payload_preview"])

    def test_payload_preview_is_bounded(self):
        preview = _safe_payload_preview({"data": "x" * 5000}, max_chars=100)
        self.assertLessEqual(len(preview), 114)
        self.assertIn("[truncated]", preview)

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
