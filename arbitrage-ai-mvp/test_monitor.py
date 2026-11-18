import unittest

from monitor import (
    allowed_vwap_change_pct,
    confirm_snapshots,
    record_paper_validations,
    route_key,
    eligible_opportunities,
)


def opportunity(buy=100, sell=102, profit=10000, net=0.5):
    return {
        "symbol": "BTC/IRT",
        "buy_exchange": "Wallex",
        "sell_exchange": "Nobitex",
        "buy_vwap": buy,
        "sell_vwap": sell,
        "base_quantity": 0.01,
        "profit_toman": profit,
        "used_capital_toman": 1_000_000,
        "net_spread_pct": net,
        "market_data_status": "داده بازار مناسب شبیه‌سازی",
        "validation_status": "فقط شبیه‌سازی؛ انتقال/شبکه تأییدنشده",
        "buy_book_age_seconds": 2,
        "sell_book_age_seconds": 3,
        "snapshot_skew_seconds": 1,
    }



class FreshnessGateTests(unittest.TestCase):
    def test_fresh_synchronized_route_is_eligible(self):
        self.assertEqual(len(eligible_opportunities({"opportunities": [opportunity()]})), 1)

    def test_stale_book_is_rejected(self):
        item = opportunity()
        item["buy_book_age_seconds"] = 91
        self.assertEqual(eligible_opportunities({"opportunities": [item]}), [])

    def test_time_skewed_snapshot_is_rejected(self):
        item = opportunity()
        item["snapshot_skew_seconds"] = 16
        self.assertEqual(eligible_opportunities({"opportunities": [item]}), [])

    def test_unvalidated_market_data_is_rejected(self):
        item = opportunity()
        item["market_data_status"] = "نیازمند بررسی داده/زمان"
        self.assertEqual(eligible_opportunities({"opportunities": [item]}), [])


    def test_stability_streak_increments_within_allowed_gap(self):
        from monitor import update_stability
        state = {"stability": {}}
        first = opportunity()
        second = opportunity(buy=100.02, sell=102.02)
        self.assertEqual(update_stability([first], state, now=1000)[route_key(first)], 1)
        self.assertEqual(update_stability([second], state, now=1300)[route_key(second)], 2)

    def test_stability_streak_resets_after_scheduler_gap(self):
        from monitor import update_stability
        state = {"stability": {}}
        item = opportunity()
        update_stability([item], state, now=1000)
        counts = update_stability([item], state, now=1000 + 901)
        self.assertEqual(counts[route_key(item)], 1)

    def test_stability_streak_resets_when_timestamp_is_missing(self):
        from monitor import update_stability
        item = opportunity()
        state = {"stability": {route_key(item): {
            "buy_vwap": 100, "sell_vwap": 102, "quantity": 0.01,
            "profit": 10000, "count": 4,
        }}}
        counts = update_stability([item], state, now=2000)
        self.assertEqual(counts[route_key(item)], 1)

class ConfirmationTests(unittest.TestCase):
    def test_margin_caps_price_change_limit_at_point_one_percent(self):
        self.assertEqual(allowed_vwap_change_pct(1.0), 0.10)

    def test_thin_margin_uses_half_net_return(self):
        self.assertEqual(allowed_vwap_change_pct(0.08), 0.04)

    def test_stable_second_snapshot_is_confirmed(self):
        first = opportunity()
        second = opportunity(buy=100.05, sell=102.04)
        confirmed, rejected = confirm_snapshots([first], [second])
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(rejected, [])

    def test_large_price_move_is_rejected(self):
        first = opportunity()
        second = opportunity(buy=100.2, sell=102)
        confirmed, rejected = confirm_snapshots([first], [second])
        self.assertEqual(confirmed, [])
        self.assertEqual(rejected[0]["reason"], "price_moved_or_profit_disappeared")

    def test_route_disappearing_is_rejected(self):
        confirmed, rejected = confirm_snapshots([opportunity()], [])
        self.assertEqual(confirmed, [])
        self.assertEqual(rejected[0]["reason"], "route_missing_on_confirmation")

    def test_paper_validation_is_cooldown_limited_and_never_real(self):
        item = opportunity()
        item["confirmation_buy_move_pct"] = 0.01
        item["confirmation_sell_move_pct"] = 0.02
        state = {"paper_validations": []}
        first = record_paper_validations([item], state, 100000)
        second = record_paper_validations([item], state, 100001)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertFalse(first[0]["real_order_placed"])
        self.assertEqual(first[0]["status"], "confirmed_public_orderbook_only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
