import unittest
from unittest.mock import patch, Mock
from account_readonly import wallex_balances, nobitex_balances, ExchangeAPIError

class ReadOnlyAccountTests(unittest.TestCase):
    @patch("account_readonly.requests.get")
    def test_wallex_balance_uses_get_and_parses_available(self, get):
        response = Mock()
        response.json.return_value = {"success": True, "result": {"balances": {
            "TMN": {"asset": "TMN", "faName": "تومان", "value": "1000", "locked": "200"}
        }}}
        response.status_code = 200
        get.return_value = response
        rows = wallex_balances("test-key")
        self.assertEqual(rows[0]["available"], 800)
        self.assertTrue(get.call_args.args[0].endswith("/v1/account/balances"))
        self.assertEqual(get.call_args.kwargs["headers"]["X-API-Key"], "test-key")

    @patch("account_readonly.requests.get")
    def test_nobitex_uses_get_and_converts_rial_to_toman(self, get):
        response = Mock()
        response.json.return_value = {"status": "ok", "wallets": [{
            "currency": "rls", "balance": "10000", "blockedBalance": "1000", "activeBalance": "9000"
        }]}
        response.status_code = 200
        get.return_value = response
        rows = nobitex_balances("test-token")
        self.assertEqual(rows[0]["asset"], "IRT")
        self.assertEqual(rows[0]["total"], 1000)
        self.assertEqual(rows[0]["available"], 900)
        self.assertTrue(get.call_args.args[0].endswith("/users/wallets/list"))

    def test_missing_credentials_are_rejected(self):
        with patch.dict("os.environ", {"WALLEX_API_KEY": "", "NOBITEX_API_TOKEN": ""}):
            with self.assertRaises(ExchangeAPIError):
                wallex_balances()
            with self.assertRaises(ExchangeAPIError):
                nobitex_balances()

if __name__ == "__main__":
    unittest.main(verbosity=2)
