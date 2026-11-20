import unittest

from run_monitor import build_report


class MonitorReportTests(unittest.TestCase):
    def test_report_explains_missing_exchange_timestamp(self):
        report = build_report(7, {
            "wallex_books": 12,
            "nobitex_books": 15,
            "common_symbols": 9,
            "accepted_count": 0,
            "rejected_count": 2,
            "opportunities": [
                {"freshness_verified": False, "eligible": False},
                {"freshness_verified": False, "eligible": False},
            ],
            "errors": [],
        })
        self.assertIn("دفترهای والکس: 12", report)
        self.assertIn("timestamp معتبر", report)
        self.assertIn("هیچ سیگنال قابل‌تأییدی", report)
        self.assertIn("هیچ سفارش، برداشت یا انتقالی", report)

    def test_report_lists_only_eligible_paper_candidates(self):
        report = build_report(8, {
            "wallex_books": 2,
            "nobitex_books": 3,
            "common_symbols": 1,
            "accepted_count": 1,
            "rejected_count": 0,
            "opportunities": [{
                "symbol": "BTC/IRT",
                "buy_exchange": "Wallex",
                "sell_exchange": "Nobitex",
                "estimated_net_profit_toman": 1200,
                "freshness_verified": True,
                "eligible": True,
            }],
            "errors": [],
        })
        self.assertIn("BTC/IRT", report)
        self.assertIn("1,200 تومان", report)
        self.assertNotIn("سیگنال واجد شرایط: 0", report)


if __name__ == "__main__":
    unittest.main()
