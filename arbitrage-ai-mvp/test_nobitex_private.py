import unittest

from nobitex_private import _wallet_rows


class WalletResponseParsingTests(unittest.TestCase):
    def test_documented_list_response(self):
        payload = {"status": "ok", "wallets": [{"currency": "rls", "balance": "0", "activeBalance": "0"}]}
        rows = _wallet_rows(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["currency"], "rls")

    def test_map_shaped_response(self):
        payload = {"status": "ok", "wallets": {"BTC": {"balance": "0.1", "blocked": "0"}}}
        rows = _wallet_rows(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["currency"], "BTC")
        self.assertEqual(rows[0]["balance"], "0.1")

    def test_empty_wallet_response(self):
        self.assertEqual(_wallet_rows({"status": "ok", "wallets": []}), [])


if __name__ == "__main__":
    unittest.main()
