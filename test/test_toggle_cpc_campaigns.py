import http.client
import pathlib
import sys
import unittest
from unittest.mock import patch, MagicMock

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from toggle_cpc_campaigns import (
    activation_filter_reason,
    is_transient_cpc_error,
    _request_with_retry,
)


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

    def test_is_transient_cpc_error(self):
        conn_err = requests.exceptions.ConnectionError(
            "Connection aborted.",
            http.client.RemoteDisconnected("Remote end closed connection without response"),
        )
        self.assertTrue(is_transient_cpc_error(conn_err))
        self.assertTrue(is_transient_cpc_error(requests.exceptions.Timeout("timed out")))
        self.assertTrue(is_transient_cpc_error(RuntimeError("POST ... -> HTTP 429: Rate limit")))
        self.assertTrue(is_transient_cpc_error(RuntimeError("POST ... -> HTTP 502: Bad Gateway")))
        self.assertFalse(is_transient_cpc_error(RuntimeError("POST ... -> HTTP 400: Bad Request")))
        self.assertFalse(is_transient_cpc_error(ValueError("Invalid argument")))

    @patch("toggle_cpc_campaigns.time.sleep", return_value=None)
    @patch("toggle_cpc_campaigns.request_json")
    def test_request_with_retry_succeeds_after_transient_connection_error(self, mock_request_json, mock_sleep):
        mock_request_json.side_effect = [
            requests.exceptions.ConnectionError(
                "Connection aborted.",
                http.client.RemoteDisconnected("Remote end closed connection without response"),
            ),
            {"status": "ok"},
        ]
        session = MagicMock()
        _request_with_retry(session, "POST", "/api/client/campaign/123/deactivate", token="fake_token", max_attempts=3)
        self.assertEqual(mock_request_json.call_count, 2)
        mock_sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
