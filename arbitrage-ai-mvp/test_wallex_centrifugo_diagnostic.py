import unittest

from wallex_centrifugo_diagnostic import CHANNELS, inspect_frame


class CentrifugoFrameTests(unittest.TestCase):
    def test_connect_ack(self):
        self.assertEqual(inspect_frame({"id": 1, "connect": {}})["kind"], "connect_ack")

    def test_subscription_ack(self):
        frame = inspect_frame({"id": 2, "subscribe": {"recoverable": False}})
        self.assertEqual(frame, {"kind": "subscribe_ack", "id": 2})

    def test_depth_publication_is_diagnostic_only(self):
        frame = inspect_frame({
            "push": {
                "channel": CHANNELS[0],
                "pub": {"data": [{"price": "1", "quantity": "2"}]},
            }
        })
        self.assertEqual(frame["kind"], "publication")
        self.assertEqual(frame["channel"], CHANNELS[0])
        self.assertEqual(frame["levels"], 1)
        self.assertEqual(frame["timestamp_fields"], [])

    def test_timestamp_fields_are_reported_not_trusted(self):
        frame = inspect_frame({
            "push": {
                "channel": CHANNELS[1],
                "pub": {"data": {"timestamp": 123, "bids": []}},
            }
        })
        self.assertEqual(frame["timestamp_fields"], ["timestamp"])

    def test_ping_and_server_error(self):
        self.assertEqual(inspect_frame({})["kind"], "ping")
        self.assertEqual(inspect_frame({"error": {"code": 1}})["kind"], "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
