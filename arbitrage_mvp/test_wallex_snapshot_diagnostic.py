import unittest
from wallex_snapshot_diagnostic import compare_snapshots


def book(price, stamp=None):
    return {
        "asks": [(price, 2.0)],
        "bids": [(price - 1, 3.0)],
        "exchange_timestamp": stamp,
    }


class WallexSnapshotDiagnosticTests(unittest.TestCase):
    def test_detects_local_observed_change_without_claiming_exchange_time(self):
        result = compare_snapshots([
            {"BTC/IRT": book(100)},
            {"BTC/IRT": book(101)},
            {"BTC/IRT": book(101)},
        ])
        self.assertEqual(result["BTC/IRT"]["changed_between_observations"], 1)
        self.assertEqual(result["BTC/IRT"]["unchanged_between_observations"], 1)
        self.assertEqual(result["BTC/IRT"]["timestamp_quality"], "local_observation_only")
        self.assertFalse(result["BTC/IRT"]["exchange_timestamp_available"])

    def test_requires_two_snapshots(self):
        with self.assertRaises(ValueError):
            compare_snapshots([{"BTC/IRT": book(100)}])

    def test_only_intersection_of_symbols_is_compared(self):
        result = compare_snapshots([
            {"BTC/IRT": book(100), "ETH/IRT": book(50)},
            {"BTC/IRT": book(100), "XRP/IRT": book(1)},
        ])
        self.assertEqual(list(result), ["BTC/IRT"])


if __name__ == "__main__":
    unittest.main()
