import unittest
from wallex_reconnect_batch import GAP_SCHEDULE, next_gap_seconds, summarize_runs


class WallexReconnectBatchTests(unittest.TestCase):
    def test_schedule_has_ten_runs_and_all_gap_lengths(self):
        self.assertEqual(len(GAP_SCHEDULE), 10)
        self.assertEqual(set(GAP_SCHEDULE), {2, 5, 10})

    def test_next_gap_advances_by_completed_count(self):
        self.assertEqual(next_gap_seconds(0), 2)
        self.assertEqual(next_gap_seconds(1), 5)
        self.assertEqual(next_gap_seconds(2), 10)

    def test_schedule_rejects_more_than_ten_runs(self):
        with self.assertRaises(IndexError):
            next_gap_seconds(10)

    def test_summary_counts_candidate_and_failed(self):
        runs = [
            {"status": "candidate", "post_rest_ws_comparison": {
                "bid": {"status": "candidate"}, "ask": {"status": "candidate"}}},
            {"status": "failed", "post_rest_ws_comparison": {
                "bid": {"status": "candidate"}, "ask": {"status": "failed"}}},
        ]
        result = summarize_runs(runs)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["candidate"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["candidate_rate_pct"], 50.0)
        self.assertEqual(result["bid_candidate"], 2)
        self.assertEqual(result["ask_candidate"], 1)
        self.assertFalse(result["scanner_feed_enabled"])
        self.assertFalse(result["execution_allowed"])


if __name__ == "__main__":
    unittest.main()
