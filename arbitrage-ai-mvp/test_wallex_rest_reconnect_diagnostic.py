import unittest
from wallex_rest_reconnect_diagnostic import _compare_side, _valid_snapshot


class RestReconnectConvergenceTests(unittest.TestCase):
    def test_matching_levels_are_candidate(self):
        result = _compare_side({"price": 100.0, "quantity": 10.0}, {"price": 100.05, "quantity": 11.0})
        self.assertEqual(result["status"], "candidate")

    def test_price_mismatch_fails(self):
        self.assertEqual(_compare_side({"price": 102, "quantity": 10}, {"price": 100, "quantity": 10})["status"], "failed")

    def test_quantity_mismatch_fails(self):
        self.assertEqual(_compare_side({"price": 100, "quantity": 15}, {"price": 100, "quantity": 10})["status"], "failed")

    def test_missing_side_fails_closed(self):
        self.assertEqual(_compare_side(None, {"price": 1, "quantity": 1})["status"], "failed")

    def test_invalid_snapshot_fails_closed(self):
        self.assertFalse(_valid_snapshot({"sides": {"bid": {"price": 1, "quantity": 1, "levels": 1}}}))

    def test_complete_snapshot_is_valid(self):
        side = {"price": 1, "quantity": 1, "levels": 1}
        self.assertTrue(_valid_snapshot({"sides": {"bid": side, "ask": side}}))


if __name__ == "__main__":
    unittest.main()
