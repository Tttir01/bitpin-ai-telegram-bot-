import os
import unittest
from unittest.mock import patch

import monitor_entrypoint


class MonitorEntrypointTests(unittest.TestCase):
    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "123"}, clear=False)
    def test_missing_token_stops_before_market_scan(self):
        with patch.object(monitor_entrypoint.monitor, "main") as main:
            with self.assertRaisesRegex(SystemExit, "TELEGRAM_BOT_TOKEN"):
                monitor_entrypoint.run()
            main.assert_not_called()

    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "123"}, clear=False)
    def test_missing_chat_id_stops_before_market_scan(self):
        with patch.object(monitor_entrypoint.monitor, "main") as main:
            with patch.dict(os.environ, {"TELEGRAM_CHAT_ID": ""}):
                with self.assertRaisesRegex(SystemExit, "TELEGRAM_CHAT_ID"):
                    monitor_entrypoint.run()
            main.assert_not_called()

    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "123"}, clear=False)
    def test_delivery_error_fails_monitor_after_main_handles_it(self):
        def fake_main():
            try:
                monitor_entrypoint.monitor.send_telegram("test")
            except RuntimeError:
                pass

        with patch.object(monitor_entrypoint.monitor, "send_telegram", side_effect=RuntimeError("Telegram unavailable")):
            with patch.object(monitor_entrypoint.monitor, "main", side_effect=fake_main):
                with self.assertRaisesRegex(RuntimeError, "Telegram delivery failed"):
                    monitor_entrypoint.run()

    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "123"}, clear=False)
    def test_successful_delivery_keeps_monitor_successful(self):
        def fake_main():
            self.assertTrue(monitor_entrypoint.monitor.send_telegram("test"))

        with patch.object(monitor_entrypoint.monitor, "send_telegram", return_value=True):
            with patch.object(monitor_entrypoint.monitor, "main", side_effect=fake_main):
                monitor_entrypoint.run()


if __name__ == "__main__":
    unittest.main(verbosity=2)
