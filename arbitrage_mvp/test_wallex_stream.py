import unittest
from wallex_stream import _stream_levels


class WallexStreamTests(unittest.TestCase):
    def test_numeric_keyed_broadcaster_payload_is_sorted(self):
        payload = {
            "1": {"price": "101", "quantity": "2"},
            "0": {"price": "100", "quantity": "1"},
        }
        self.assertEqual(_stream_levels(payload, "ask"), [(100.0, 1.0), (101.0, 2.0)])

    def test_bid_levels_are_descending(self):
        payload = [
            {"price": "99", "quantity": "1"},
            {"price": "102", "quantity": "3"},
        ]
        self.assertEqual(_stream_levels(payload, "bid"), [(102.0, 3.0), (99.0, 1.0)])


if __name__ == "__main__":
    unittest.main()
