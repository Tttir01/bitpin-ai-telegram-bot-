import unittest

from monitor import (
    allowed_vwap_change_pct,
    confirm_snapshots,
    record_paper_validations,
    route_key,
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
    }


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
