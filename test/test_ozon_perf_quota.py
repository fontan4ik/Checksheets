import concurrent.futures
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ozon_perf_quota as quota
import ozon_cpc_cleanup as cleanup


def response(status=200, text='', headers=None):
    result = Mock(status_code=status, text=text, headers=headers or {})
    result.content = b'{}'
    result.json.return_value = {}
    return result


class PerformanceQuotaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'quota.json'
        state = patch.object(quota, 'STATE_PATH', self.path)
        state.start()
        self.addCleanup(state.stop)
        clock = patch.object(quota.time, 'time', return_value=10000)
        self.clock = clock.start()
        self.addCleanup(clock.stop)

    def exhausted(self, headers=None):
        return response(400, '{"error":"The request limit has been reached: 100000 request per 24h0m0s"}', headers)

    def block(self):
        with self.assertRaises(quota.PerformanceQuotaError) as caught:
            quota.request_with_quota(lambda: self.exhausted())
        return caught.exception

    def test_stops_next_job_before_another_network_request(self):
        first = self.block()
        self.assertTrue(first.newly_blocked)
        call = Mock()
        with self.assertRaises(quota.PerformanceQuotaError) as second:
            quota.request_with_quota(call)
        call.assert_not_called()
        self.assertFalse(second.exception.newly_blocked)

    def test_report_limit_and_short_rate_limit_do_not_block_account(self):
        for result in [response(429, 'Превышен дневной лимит создания отчётов'),
                       response(429, 'rate limit 10 requests per second'),
                       response(400, 'invalid campaign'), response(401, 'unauthorized')]:
            self.assertIs(quota.request_with_quota(lambda: result), result)
        self.assertIsNotNone(quota.request_with_quota(lambda: response()))

    def test_failed_probe_extends_cooldown_without_repeated_alert(self):
        first = self.block()
        self.clock.return_value = first.retry_at + 1
        second = self.block()
        self.assertFalse(second.newly_blocked)
        self.assertGreater(second.retry_at, first.retry_at)

    def test_any_concurrent_observer_can_claim_episode_alert_once(self):
        self.block()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda _: quota.claim_quota_alert(), range(8)))
        self.assertEqual(sum(claims), 1)
        self.clock.return_value += quota.COOLDOWN_SECONDS + 1
        self.block()
        self.assertFalse(quota.claim_quota_alert())

    def test_next_episode_after_recovery_can_alert_again(self):
        self.clock.return_value = self.block().retry_at + 1
        self.assertTrue(quota.claim_quota_alert())
        quota.request_with_quota(lambda: response())
        self.block()
        self.assertTrue(quota.claim_quota_alert())

    def test_successful_probe_reopens_account(self):
        self.clock.return_value = self.block().retry_at + 1
        quota.request_with_quota(lambda: response())
        call = Mock(return_value=response())
        quota.request_with_quota(call)
        call.assert_called_once()
        self.assertTrue(self.block().newly_blocked)

    def test_retry_after_header_respected(self):
        with self.assertRaises(quota.PerformanceQuotaError) as error:
            quota.request_with_quota(lambda: self.exhausted({'Retry-After': '3600'}))
        self.assertEqual(error.exception.retry_at, 13600)

    def test_only_one_probe_reserved_for_concurrent_jobs(self):
        self.clock.return_value = self.block().retry_at + 1
        def reserve(_):
            try:
                return quota._reserve_probe()
            except quota.PerformanceQuotaError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            probes = list(pool.map(reserve, range(8)))
        self.assertEqual(sum(p is not None for p in probes), 1)

    def test_dead_probe_lease_expires(self):
        self.clock.return_value = self.block().retry_at + 1
        first = quota._reserve_probe()
        self.clock.return_value += quota.PROBE_LEASE_SECONDS + 1
        self.assertNotEqual(quota._reserve_probe(), first)

    def test_failed_probe_network_error_keeps_cooldown(self):
        self.clock.return_value = self.block().retry_at + 1
        with self.assertRaises(TimeoutError):
            quota.request_with_quota(Mock(side_effect=TimeoutError))
        call = Mock()
        with self.assertRaises(quota.PerformanceQuotaError):
            quota.request_with_quota(call)
        call.assert_not_called()

    def test_authentication_success_does_not_reopen_quota(self):
        self.block()
        cleanup.request_json(Mock(request=Mock(return_value=response())), 'POST', '/api/client/token')
        call = Mock()
        with self.assertRaises(quota.PerformanceQuotaError):
            quota.request_with_quota(call)
        call.assert_not_called()

    def test_shared_http_client_does_not_retry_general_quota(self):
        call = Mock(return_value=self.exhausted())
        with self.assertRaises(quota.PerformanceQuotaError):
            cleanup.request_json(Mock(request=call), 'GET', '/api/client/campaign')
        call.assert_called_once()


if __name__ == '__main__':
    unittest.main()
