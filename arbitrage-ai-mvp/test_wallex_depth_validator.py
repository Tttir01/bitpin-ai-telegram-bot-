import unittest
from wallex_depth_validator import _side_summary, _pct_diff


def event(t, price, qty, levels=50, fields=None):
    return {"side": "bid", "received_after_start_ms": t, "price": price,
            "quantity": qty, "levels": levels, "metadata_fields": fields or []}


def snapshot(price, qty):
    return {"sides": {"bid": {"price": price, "quantity": qty}}}


class DepthValidatorUnitTests(unittest.TestCase):
    def test_percent_diff(self):
        self.assertAlmostEqual(_pct_diff(101, 100), 1.0)
        self.assertIsNone(_pct_diff(None, 100))

    def test_first_and_last_are_separately_tracked(self):
        events = [event(10, 100, 5), event(20, 100, 6), event(30, 101, 7)]
        result = _side_summary(events, snapshot(101, 7), snapshot(101, 7), 3)
        self.assertEqual(result["first"]["quantity"], 5)
        self.assertEqual(result["last"]["quantity"], 7)
        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(result["top_price_changes"], 1)
        self.assertEqual(result["status"], "candidate")

    def test_insufficient_messages_fails(self):
        result = _side_summary([event(10, 100, 5)], snapshot(100, 5), snapshot(100, 5), 10)
        self.assertEqual(result["status"], "failed")

    def test_empty_channel_fails(self):
        self.assertEqual(_side_summary([], None, None, 1)["status"], "failed")

    def test_zero_levels_and_no_comparable_rest_fail(self):
        result = _side_summary([event(1, 100, 5, levels=0)], None, None, 1)
        self.assertEqual(result["status"], "failed")

    def test_metadata_fields_are_reported_not_certified(self):
        events = [event(i, 100, 5, fields=["offset"]) for i in range(1, 3)]
        result = _side_summary(events, snapshot(100, 5), snapshot(100, 5), 2)
        self.assertEqual(result["timestamp_or_sequence_fields_seen"], ["offset"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
