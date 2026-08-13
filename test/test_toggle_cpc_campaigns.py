import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from toggle_cpc_campaigns import activation_filter_reason


class ToggleCpcCampaignsTests(unittest.TestCase):
    def test_blocks_activation_when_day_click_filter_is_reached(self):
        reason = activation_filter_reason(
            clicks_day="18",
            filter_clicks_day="10",
            drr_month="0",
            filter_drr_month="5",
        )
        self.assertEqual(reason, "клики день=18 >= фильтр=10")

    def test_blocks_activation_when_month_drr_filter_is_reached(self):
        reason = activation_filter_reason(
            clicks_day="2",
            filter_clicks_day="10",
            drr_month="12.5",
            filter_drr_month="5",
        )
        self.assertEqual(reason, "ДРР месяц=12.5 >= фильтр=5")

    def test_allows_activation_when_filters_are_not_reached(self):
        reason = activation_filter_reason(
            clicks_day="9",
            filter_clicks_day="10",
            drr_month="4.9",
            filter_drr_month="5",
        )
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
