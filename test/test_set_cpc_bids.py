import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from set_cpc_bids import (
    BidReadError,
    BidWriteError,
    BidRow,
    bid_row_key,
    get_bid,
    main,
    observed_desired_bids,
    parse_bid_microrubles,
    put_bid,
    read_bid_rows,
    select_bid_plan,
    select_bid_rows,
)
import ozon_perf_quota


class SetCpcBidsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.quota_path = pathlib.Path(self.temporary.name) / "quota.json"
        self.quota_patch = patch.object(ozon_perf_quota, "STATE_PATH", self.quota_path)
        self.quota_patch.start()
        self.addCleanup(self.quota_patch.stop)

    @staticmethod
    def rows(count):
        return [BidRow(i + 2, str(i), str(10000 + i), 8_000_000) for i in range(count)]

    @staticmethod
    def initialized_state(rows):
        return {
            "initialized": True,
            "desired": {bid_row_key(row): row.bid_microrubles for row in rows},
            "failed": [],
        }

    def run_fake(self, rows, state, session):
        state_file = pathlib.Path(self.temporary.name) / "bid-state.json"
        state_file.write_text(json.dumps(state))
        values = [["SKU OZON", "CAMPAIN ID", "Размер ставки"]] + [
            [row.sku, row.campaign_id, str(row.bid_microrubles / 1_000_000)] for row in rows
        ]
        worksheet = Mock(get_all_values=Mock(return_value=values))
        output = io.StringIO()
        with patch("sys.argv", ["set_cpc_bids.py", "--apply", "--state-file", str(state_file)]), \
                patch("set_cpc_bids.gsheets_utils.get_worksheet", return_value=worksheet), \
                patch("set_cpc_bids.gsheets_utils._retry_gsheet_call", side_effect=lambda _, call: call()), \
                patch("set_cpc_bids.create_session", return_value=session), \
                patch("set_cpc_bids.get_token", return_value="token"), \
                contextlib.redirect_stdout(output):
            code = main()
        return code, json.loads(state_file.read_text()), output.getvalue()

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

    def test_first_cached_run_only_audits_rotating_batch(self):
        rows = [BidRow(i + 2, str(i), str(100 + i), 8_000_000) for i in range(5)]
        selected, desired, cursor = select_bid_rows(rows, {}, audit_batch_size=2)
        self.assertEqual([row.campaign_id for row in selected], ["0", "1"])
        self.assertEqual(len(desired), 5)
        self.assertEqual(cursor, 2)

    def test_changed_and_failed_rows_are_prioritized_without_duplicates(self):
        rows = [BidRow(i + 2, str(i), str(100 + i), 8_000_000) for i in range(5)]
        state = {
            "initialized": True,
            "desired": {f"{i}:{100 + i}": 8_000_000 for i in range(5)},
            "failed": ["3:103"],
            "audit_cursor": 2,
        }
        rows[1] = BidRow(3, "1", "101", 16_000_000)
        selected, _, cursor = select_bid_rows(rows, state, audit_batch_size=2)
        self.assertEqual([row.campaign_id for row in selected], ["1", "3", "2"])
        self.assertEqual(cursor, 4)

    def test_full_audit_selects_every_row(self):
        rows = [BidRow(i + 2, str(i), str(100 + i), 8_000_000) for i in range(3)]
        selected, _, cursor = select_bid_rows(rows, {}, audit_batch_size=1, full_audit=True)
        self.assertEqual(selected, rows)
        self.assertEqual(cursor, 0)

    def test_large_failed_queue_is_bounded_and_rotates_independently(self):
        rows = self.rows(1932)
        state = self.initialized_state(rows)
        state.update(failed=[bid_row_key(row) for row in rows], audit_cursor=100)
        selected, _, audit_cursor, retry_cursor = select_bid_plan(rows, state)
        self.assertEqual(len(selected), 40)
        self.assertEqual(selected[:20], rows[:20])
        self.assertEqual(selected[20:], rows[100:120])
        self.assertEqual((audit_cursor, retry_cursor), (120, 20))
        state.update(audit_cursor=audit_cursor, retry_cursor=retry_cursor)
        selected, _, _, retry_cursor = select_bid_plan(rows, state)
        self.assertEqual(selected[:20], rows[20:40])
        self.assertEqual(retry_cursor, 40)

    def test_total_cap_keeps_unprocessed_sheet_changes_pending(self):
        rows = self.rows(250)
        state = self.initialized_state(rows)
        state["desired"] = {bid_row_key(row): 4_000_000 for row in rows}
        selected, desired, audit_cursor, retry_cursor = select_bid_plan(rows, state)
        self.assertEqual(selected, rows[:100])
        state["desired"] = observed_desired_bids(
            desired, state, {bid_row_key(row) for row in selected}
        )
        state.update(audit_cursor=audit_cursor, retry_cursor=retry_cursor)
        selected_next, _, _, _ = select_bid_plan(rows, state)
        self.assertEqual(selected_next, rows[100:200])
        self.assertEqual(state["desired"][bid_row_key(rows[249])], 4_000_000)

    def test_changed_bid_has_priority_over_failed_and_audit_rows(self):
        rows = self.rows(200)
        state = self.initialized_state(rows)
        state["failed"] = [bid_row_key(row) for row in rows]
        rows[-1] = BidRow(rows[-1].row_number, rows[-1].campaign_id, rows[-1].sku, 9_000_000)
        selected, _, _, _ = select_bid_plan(rows, state, max_rows=1)
        self.assertEqual(selected, [rows[-1]])

    def test_new_changed_keys_beyond_cap_are_not_marked_observed(self):
        rows = self.rows(3)
        state = {"initialized": True, "desired": {}}
        selected, desired, _, _ = select_bid_plan(rows, state, max_rows=1)
        observed = observed_desired_bids(desired, state, {bid_row_key(row) for row in selected})
        self.assertEqual(observed, {bid_row_key(rows[0]): 8_000_000})
        self.assertNotIn(bid_row_key(rows[1]), observed)

    def test_successful_retry_removal_does_not_reset_retry_cursor_to_queue_front(self):
        rows = self.rows(100)
        state = self.initialized_state(rows)
        state["failed"] = [bid_row_key(row) for row in rows]
        selected, _, _, retry_cursor = select_bid_plan(rows, state, audit_batch_size=0)
        state.update(failed=[bid_row_key(row) for row in rows[20:]], retry_cursor=retry_cursor)
        selected_next, _, _, _ = select_bid_plan(rows, state, audit_batch_size=0)
        self.assertEqual(selected, rows[:20])
        self.assertEqual(selected_next, rows[20:40])

    def test_write_failure_reports_http_and_redacts_token(self):
        response = Mock(status_code=400, text="bad bid; bearer secret-token; secret-token")
        session = Mock(put=Mock(return_value=response))
        with self.assertRaises(BidWriteError) as raised:
            put_bid(session, "secret-token", "1", "2", 8_000_000)
        self.assertIn("HTTP 400: bad bid", str(raised.exception))
        self.assertNotIn("secret-token", str(raised.exception))
        self.assertEqual(raised.exception.attempts, 1)
        session.put.assert_called_once()

    def test_quota_aborts_queued_rows_without_writes_or_cache_overwrite(self):
        rows = self.rows(1000)
        state = self.initialized_state(rows)
        state["failed"] = [bid_row_key(row) for row in rows]
        state_file = pathlib.Path(self.temporary.name) / "bid-state.json"
        state_file.write_text(json.dumps(state))
        original_state = state_file.read_bytes()
        quota = Mock(status_code=400, text='{"error":"The request limit has been reached: 100000 request per 24h0m0s"}', headers={})
        session = Mock(get=Mock(return_value=quota))
        values = [["SKU OZON", "CAMPAIN ID", "Размер ставки"]] + [
            [row.sku, row.campaign_id, "8"] for row in rows
        ]
        worksheet = Mock(get_all_values=Mock(return_value=values))
        with patch("sys.argv", ["set_cpc_bids.py", "--apply", "--state-file", str(state_file)]), \
                patch("set_cpc_bids.gsheets_utils.get_worksheet", return_value=worksheet), \
                patch("set_cpc_bids.gsheets_utils._retry_gsheet_call", side_effect=lambda _, call: call()), \
                patch("set_cpc_bids.create_session", return_value=session), \
                patch("set_cpc_bids.get_token", return_value="token"), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 1)
        session.get.assert_called_once()
        session.put.assert_not_called()
        self.assertEqual(state_file.read_bytes(), original_state)

    def test_existing_quota_cooldown_is_a_quiet_deferred_run(self):
        error = ozon_perf_quota.PerformanceQuotaError(1234567890, newly_blocked=False)
        with patch("set_cpc_bids.run", side_effect=error), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)

    def test_cooldown_future_can_claim_first_episode_alert_once(self):
        # Worker completion order need not expose the original newly_blocked
        # exception first; alert ownership belongs to the shared episode state.
        self.quota_path.write_text(json.dumps({
            "blocked_since": 1,
            "retry_at": 1234567890,
            "alert_pending": True,
        }))
        error = ozon_perf_quota.PerformanceQuotaError(1234567890, newly_blocked=False)
        with patch("set_cpc_bids.run", side_effect=error), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 1)
            self.assertEqual(main(), 0)

    def test_failed_read_never_updates_bid(self):
        rows = self.rows(1)
        state = self.initialized_state(rows)
        state_file = pathlib.Path(self.temporary.name) / "bid-state.json"
        state_file.write_text(json.dumps(state))
        session = Mock(get=Mock(return_value=Mock(status_code=400, text="bad request")))
        worksheet = Mock(get_all_values=Mock(return_value=[
            ["SKU OZON", "CAMPAIN ID", "Размер ставки"],
            [rows[0].sku, rows[0].campaign_id, "8"],
        ]))
        with patch("sys.argv", ["set_cpc_bids.py", "--apply", "--state-file", str(state_file)]), \
                patch("set_cpc_bids.gsheets_utils.get_worksheet", return_value=worksheet), \
                patch("set_cpc_bids.gsheets_utils._retry_gsheet_call", side_effect=lambda _, call: call()), \
                patch("set_cpc_bids.create_session", return_value=session), \
                patch("set_cpc_bids.get_token", return_value="token"), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 1)
        session.put.assert_not_called()

    def test_rejected_range_is_excluded_from_failed_retry_and_audit(self):
        rows = self.rows(2)
        key = bid_row_key(rows[0])
        state = self.initialized_state(rows)
        state.update(failed=[key], rejected={key: {
            "desired_bid": 8_000_000, "reason": "bad range", "retry_at": 9999999999,
        }})
        selected, _, _, _ = select_bid_plan(rows, state)
        self.assertEqual(selected, [rows[1]])
        full, _, _, _ = select_bid_plan(rows, state, full_audit=True)
        self.assertEqual(full, [rows[1]])

    def test_rejected_value_changes_bypass_quarantine_immediately(self):
        rows = self.rows(1)
        key = bid_row_key(rows[0])
        state = self.initialized_state(rows)
        state["rejected"] = {key: {
            "desired_bid": 8_000_000, "reason": "bad range", "retry_at": 9999999999,
        }}
        rows[0] = BidRow(2, rows[0].campaign_id, rows[0].sku, 9_000_000)
        selected, _, _, _ = select_bid_plan(rows, state, audit_batch_size=0)
        self.assertEqual(selected, rows)

    def test_expired_rejection_enters_bounded_retry_without_audit(self):
        rows = self.rows(30)
        state = self.initialized_state(rows)
        state["rejected"] = {bid_row_key(row): {
            "desired_bid": row.bid_microrubles, "reason": "bad range", "retry_at": 1,
        } for row in rows}
        selected, _, _, _ = select_bid_plan(rows, state, audit_batch_size=0)
        self.assertEqual(selected, rows[:20])

    def test_new_invalid_range_is_saved_and_alerts_once_without_changing_desired(self):
        rows = self.rows(1)
        key = bid_row_key(rows[0])
        state = self.initialized_state(rows)
        state["failed"] = [key]
        current = Mock(status_code=200)
        current.json.return_value = {"products": [{"sku": rows[0].sku, "bid": "10000000"}]}
        response = Mock(status_code=400, text=json.dumps({
            "error": "Ставка не входит в диапазон допустимых значений",
        }))
        session = Mock(get=Mock(return_value=current), put=Mock(return_value=response))
        code, saved, output = self.run_fake(rows, state, session)
        self.assertEqual(code, 1)
        self.assertEqual(saved["desired"][key], 8_000_000)
        self.assertEqual(saved["failed"], [])
        self.assertEqual(saved["rejected"][key]["desired_bid"], 8_000_000)
        self.assertGreater(saved["rejected"][key]["retry_at"], 1)
        self.assertIn("new_rejected=1", output)
        session.put.assert_called_once()
        session.reset_mock()
        code, saved_again, output = self.run_fake(rows, saved, session)
        self.assertEqual(code, 0)
        self.assertEqual(saved_again["rejected"], saved["rejected"])
        self.assertIn("skipped_invalid=1", output)
        session.get.assert_not_called()
        session.put.assert_not_called()

    def test_same_rejection_on_daily_retry_does_not_alert_again(self):
        rows = self.rows(1)
        key = bid_row_key(rows[0])
        reason = 'HTTP 400: {"error":"Ставка не входит в диапазон допустимых значений"}'
        state = self.initialized_state(rows)
        state["rejected"] = {key: {"desired_bid": 8_000_000, "reason": reason, "retry_at": 1}}
        current = Mock(status_code=200)
        current.json.return_value = {"products": [{"sku": rows[0].sku, "bid": "10000000"}]}
        session = Mock(get=Mock(return_value=current), put=Mock(return_value=Mock(
            status_code=400, text=reason.split(": ", 1)[1],
        )))
        code, saved, output = self.run_fake(rows, state, session)
        self.assertEqual(code, 0)
        self.assertIn("new_rejected=0", output)
        self.assertGreater(saved["rejected"][key]["retry_at"], 1)

    def test_successful_retry_removes_rejection(self):
        rows = self.rows(1)
        key = bid_row_key(rows[0])
        state = self.initialized_state(rows)
        state["rejected"] = {key: {"desired_bid": 8_000_000, "reason": "bad range", "retry_at": 1}}
        current = Mock(status_code=200)
        current.json.return_value = {"products": [{"sku": rows[0].sku, "bid": "8000000"}]}
        session = Mock(get=Mock(return_value=current))
        code, saved, _ = self.run_fake(rows, state, session)
        self.assertEqual(code, 0)
        self.assertEqual(saved["rejected"], {})
        session.put.assert_not_called()

    def test_other_permanent_write_error_still_fails_without_quarantine(self):
        rows = self.rows(1)
        state = self.initialized_state(rows)
        current = Mock(status_code=200)
        current.json.return_value = {"products": [{"sku": rows[0].sku, "bid": "10000000"}]}
        session = Mock(get=Mock(return_value=current), put=Mock(return_value=Mock(
            status_code=400, text='{"error":"campaign not found"}',
        )))
        code, saved, output = self.run_fake(rows, state, session)
        self.assertEqual(code, 1)
        self.assertEqual(saved["rejected"], {})
        self.assertEqual(saved["failed"], [bid_row_key(rows[0])])
        self.assertIn("put_failed(HTTP 400", output)


if __name__ == "__main__":
    unittest.main()
