import pathlib
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from set_cpc_bids import BidReadError, get_bid, parse_bid_microrubles, read_bid_rows


class SetCpcBidsTests(unittest.TestCase):

    def test_get_bid_distinguishes_missing_sku_from_failed_request(self):
        missing = Mock(status_code=200)
        missing.json.return_value = {"products": []}
        self.assertIsNone(get_bid(Mock(get=Mock(return_value=missing)), "token", "1", "2"))

        failed = Mock(status_code=400, text="bad request")
        with self.assertRaises(BidReadError):
            get_bid(Mock(get=Mock(return_value=failed)), "token", "1", "2")

    def test_parse_bid_microrubles_supports_ruble_formats(self):
        self.assertEqual(parse_bid_microrubles("8"), 8_000_000)
        self.assertEqual(parse_bid_microrubles("16,50"), 16_500_000)
        self.assertEqual(parse_bid_microrubles(" 1.25 "), 1_250_000)

    def test_parse_bid_microrubles_rejects_unsafe_values(self):
        for value in ("", "abc", "0", "-1", "0,0000001"):
            self.assertIsNone(parse_bid_microrubles(value))

    def test_read_bid_rows_uses_ad_header_and_skips_empty_values(self):
        values = [
            ["SKU OZON", "CAMPAIN ID", "Размер ставки"],
            ["101", "201", "8"],
            ["102", "202", ""],
            ["103", "203", "16,5"],
            ["104", "204", "wrong"],
        ]
        rows, invalid = read_bid_rows(values)
        self.assertEqual(
            [(row.row_number, row.campaign_id, row.sku, row.bid_microrubles) for row in rows],
            [(2, "201", "101", 8_000_000), (4, "203", "103", 16_500_000)],
        )
        self.assertEqual(invalid, [(5, "wrong")])


if __name__ == "__main__":
    unittest.main()
