import unittest

from wallex_reconnect_diagnostic import _phase_ok


class ReconnectProbeTests(unittest.TestCase):
    def valid_phase(self):
        return {
            "connected": True,
            "subscribe_acks": 2,
            "both_sides_received": True,
            "publication_counts": {"bid": 3, "ask": 2},
        }

    def test_valid_phase_passes(self):
        self.assertTrue(_phase_ok(self.valid_phase()))

    def test_missing_side_fails(self):
        phase = self.valid_phase()
        phase["publication_counts"]["ask"] = 0
        self.assertFalse(_phase_ok(phase))

    def test_missing_subscription_ack_fails(self):
        phase = self.valid_phase()
        phase["subscribe_acks"] = 1
        self.assertFalse(_phase_ok(phase))

    def test_no_connection_fails(self):
        phase = self.valid_phase()
        phase["connected"] = False
        self.assertFalse(_phase_ok(phase))


if __name__ == "__main__":
    unittest.main(verbosity=2)
