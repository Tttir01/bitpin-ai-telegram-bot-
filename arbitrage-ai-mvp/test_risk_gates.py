import unittest

from risk_gates import (
    is_paper_candidate, profit_change_warning,
    MAX_VWAP_CHANGE_PCT, MAX_MATCHED_VOLUME_CHANGE_PCT,
    MAX_STABILITY_PROFIT_DROP_PCT, PROFIT_DROP_WARNING_PCT,
    PAPER_BLOCK_PROFIT_DROP_PCT,
)


class RiskThresholdConfigurationTests(unittest.TestCase):
    def test_thresholds_are_explicit_and_distinct(self):
        self.assertEqual(MAX_VWAP_CHANGE_PCT, 0.30)
        self.assertEqual(MAX_MATCHED_VOLUME_CHANGE_PCT, 25.0)
        self.assertEqual(MAX_STABILITY_PROFIT_DROP_PCT, 30.0)
        self.assertEqual(PROFIT_DROP_WARNING_PCT, 3.0)
        self.assertEqual(PAPER_BLOCK_PROFIT_DROP_PCT, 5.0)


class ProfitWarningTests(unittest.TestCase):
    def test_three_percent_drop_warns(self):
        self.assertIn("هشدار", profit_change_warning(-3.0))

    def test_four_percent_drop_warns_but_is_not_block_threshold(self):
        self.assertIn("هشدار", profit_change_warning(-4.0))
        self.assertTrue(candidate(profit_change_pct=-4.0))

    def test_no_comparison_snapshot_has_no_warning(self):
        self.assertIn("در انتظار", profit_change_warning(None))


class PaperTradeGateTests(unittest.TestCase):
    def test_exact_five_percent_drop_is_blocked(self):
        self.assertFalse(candidate(profit_change_pct=-5.0))

    def test_stress_profit_zero_or_negative_is_blocked(self):
        self.assertFalse(candidate(stress_profit_slip_025_toman=0))
        self.assertFalse(candidate(stress_profit_slip_025_toman=-1))

    def test_all_valid_conditions_pass(self):
        self.assertTrue(candidate())

    def test_less_than_five_scans_is_blocked(self):
        self.assertFalse(candidate(stable_scans=4))

    def test_unstable_market_is_blocked(self):
        self.assertFalse(candidate(market_stable_now=False))

    def test_insufficient_capital_is_blocked(self):
        self.assertFalse(candidate(used_capital_toman=2_000_001))


def candidate(**overrides):
    values = {
        "stable_scans": 5,
        "market_stable_now": True,
        "validation_status": "فقط شبیه‌سازی؛ انتقال/شبکه تأییدنشده",
        "profit_toman": 10_000,
        "used_capital_toman": 1_000_000,
        "capital": 2_000_000,
        "profit_change_pct": 0.0,
        "stress_profit_slip_025_toman": 100,
    }
    values.update(overrides)
    return is_paper_candidate(**values)


if __name__ == "__main__":
    unittest.main(verbosity=2)
