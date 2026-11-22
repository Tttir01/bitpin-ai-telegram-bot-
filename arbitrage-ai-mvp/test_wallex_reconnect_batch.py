import json
import tempfile
import unittest
from pathlib import Path

from wallex_reconnect_batch import (
    GAP_SCHEDULE,
    clear_runs,
    import_runs_json,
    load_runs,
    next_gap_seconds,
    save_run,
    summarize_runs,
)


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
        self.assertFalse(result["gap_recovery_verified"])
        self.assertFalse(result["sequence_order_verified"])

    def test_runs_persist_after_database_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "validation.sqlite3")
            sample = {
                "run_number": 1,
                "recorded_at_utc": "2026-11-22T12:00:00+00:00",
                "gap_seconds": 2,
                "status": "candidate",
                "post_rest_ws_comparison": {"bid": {"status": "candidate"}},
            }
            save_run(sample, database)
            self.assertEqual(load_runs(database), [sample])

    def test_json_report_import_restores_runs_and_skips_identical_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "validation.sqlite3")
            run = {"run_number": 1, "recorded_at_utc": "2026-11-22T12:00:00+00:00",
                   "gap_seconds": 2, "status": "failed"}
            report = json.dumps({"summary": {}, "runs": [run]})
            first = import_runs_json(report, database)
            second = import_runs_json(report, database)
            self.assertEqual(first, {"imported": 1, "skipped": 0, "conflicts": 0})
            self.assertEqual(second, {"imported": 0, "skipped": 1, "conflicts": 0})
            self.assertEqual(load_runs(database), [run])

    def test_json_import_does_not_overwrite_conflicting_run(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "validation.sqlite3")
            original = {"run_number": 1, "gap_seconds": 2, "status": "failed"}
            changed = {"run_number": 1, "gap_seconds": 2, "status": "candidate"}
            save_run(original, database)
            result = import_runs_json({"runs": [changed]}, database)
            self.assertEqual(result, {"imported": 0, "skipped": 0, "conflicts": 1})
            self.assertEqual(load_runs(database), [original])

    def test_json_import_rejects_wrong_gap_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "validation.sqlite3")
            with self.assertRaises(ValueError):
                import_runs_json({"runs": [{"run_number": 1, "gap_seconds": 5}]}, database)

    def test_json_import_requires_runs_array(self):
        with self.assertRaises(ValueError):
            import_runs_json({"summary": {}})

    def test_clear_runs_removes_saved_results(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "validation.sqlite3")
            save_run({"run_number": 1, "status": "failed"}, database)
            clear_runs(database)
            self.assertEqual(load_runs(database), [])


if __name__ == "__main__":
    unittest.main()
